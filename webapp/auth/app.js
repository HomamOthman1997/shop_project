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
let activeOwnerTab = "overview";
let ownerCatalogParentId = "";
let ownerDashboardLoadId = 0;
let ownerAuditFilters = {q: "", action: "", target_type: ""};
let ownerUserRows = [];
let ownerUserQuery = "";
let ownerResellerRows = [];
let ownerResellerQuery = "";
let ownerPagedRows = {};
let ownerIntegrationPayloads = {};
let ownerSystemStatusPayload = {};
let ownerProviderPayloads = {};
let customerOrderRows = [];
let customerOrderFilter = "all";
let latestRechargePayload = null;

const customerRoutes = {
  home: "/app",
  orders: "/app/orders",
  recharge: "/app/recharge",
  support: "/app/support",
  account: "/app/account",
  identity: "/app/identity",
  workspace: "/app/services",
};

const adminRoutes = {
  overview: "/admin",
  finance: "/admin/finance",
  users: "/admin/users",
  support: "/admin/support",
  integrations: "/admin/integrations",
  providers: "/admin/providers",
  catalog: "/admin/catalog",
  system: "/admin/system",
  orders: "/admin/orders",
};

const customerViewTitles = {
  home: "الخدمات",
  orders: "طلباتي",
  recharge: "شحن الرصيد",
  support: "الدعم",
  account: "حسابي",
  identity: "تأكيد الهوية",
  workspace: "الخدمة",
};

const ownerTabTitles = {
  overview: "النظرة العامة",
  finance: "المالية",
  users: "المستخدمون",
  support: "الدعم",
  integrations: "API",
  providers: "المزودون",
  catalog: "Catalog",
  system: "النظام",
  orders: "الطلبات",
};

function setPageTitle(title) {
  const clean = String(title || "Phantom Services").trim() || "Phantom Services";
  setText("#view-title", clean);
  document.title = `${clean} | Phantom`;
  window.PhantomI18n?.translatePage?.();
}

function routeForView(view) {
  return customerRoutes[view] || "/app";
}

function viewForPath(pathname = window.location.pathname) {
  if (pathname.startsWith("/app/digital")) return "digital";
  if (pathname.startsWith("/app/numbers")) return "numbers";
  if (pathname.startsWith("/app/orders")) return "orders";
  if (pathname.startsWith("/app/recharge")) return "recharge";
  if (pathname.startsWith("/app/support")) return "support";
  if (pathname.startsWith("/app/account")) return "account";
  if (pathname.startsWith("/app/identity")) return "identity";
  if (pathname.startsWith("/app/services")) return "workspace";
  return "home";
}

function ownerTabForPath(pathname = window.location.pathname) {
  if (pathname.startsWith("/admin/finance")) return "finance";
  if (pathname.startsWith("/admin/users")) return "users";
  if (pathname.startsWith("/admin/support")) return "support";
  if (pathname.startsWith("/admin/integrations")) return "integrations";
  if (pathname.startsWith("/admin/providers")) return "providers";
  if (pathname.startsWith("/admin/catalog")) return "catalog";
  if (pathname.startsWith("/admin/system")) return "system";
  if (pathname.startsWith("/admin/orders")) return "orders";
  return "overview";
}

function pushRoute(path) {
  if (window.location.pathname !== path) window.history.pushState({}, "", path);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function safeExternalUrl(value) {
  try {
    const url = new URL(String(value || "").trim());
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_error) {
    return "";
  }
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

const OWNER_API_TIMEOUT_MS = 45000;

function ownerApi(path, options = {}) {
  return api(path, {timeoutMs: OWNER_API_TIMEOUT_MS, ...options});
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
  accountView.classList.toggle("admin-mode", Boolean(account.is_owner));
  setText("#account-email", account.email);
  setText("#settings-email", account.email);
  setText("#customer-id", account.customer_id);
  setText("#telegram-status", account.telegram_linked ? "مربوط" : "غير مربوط");
  telegramAction.textContent = account.telegram_linked ? "فك الربط" : "ربط Telegram";
  document.querySelectorAll(".owner-nav").forEach((item) => { item.hidden = !account.is_owner; });
  applyEmailState(account);
  applyIdentityState(account.identity_status);
  if (account.is_owner) {
    const tab = ownerTabForPath(window.location.pathname);
    activeOwnerTab = tab;
    if (!window.location.pathname.startsWith("/admin")) pushRoute(adminRoutes[tab] || "/admin");
    openPanel("owner", "لوحة الإدارة", { updateRoute: false });
    applyOwnerTab(tab, false);
    loadOwnerDashboard();
    return;
  }
  if (window.location.pathname.startsWith("/admin")) pushRoute("/app");
  const initialView = viewForPath();
  if (initialView === "digital" || initialView === "numbers") {
    openPanel("home", "الخدمات", { updateRoute: false });
    openService(initialView);
  } else {
    openPanel(initialView, "", { updateRoute: false });
  }
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
    const [digitalAccount, digitalOrders, numberOrders, recharge, rechargeRequests, support] = await Promise.all([
      api("/api/v1/digital/account"),
      api("/api/v1/digital/orders?limit=20"),
      api("/api/v1/numbers/orders?limit=20"),
      api("/api/v1/numbers/recharge"),
      api("/api/v1/numbers/recharge/requests?limit=10"),
      api("/api/v1/numbers/support"),
    ]);
    setText("#wallet-balance", digitalAccount.wallet?.balance_label || "$0.00");
    setText("#recharge-wallet-balance", digitalAccount.wallet?.balance_label || "$0.00");

    const digitalRows = digitalOrders.orders || digitalOrders.items || [];
    const numberRows = numberOrders.orders || numberOrders.items || [];
    setText("#digital-order-count", digitalRows.length);
    setText("#numbers-order-count", numberRows.length);

    renderRows(activity, digitalAccount.recent_activity || [], (row) => `
      <div class="data-row">
        <div><strong>${esc(row.reason || "حركة رصيد")}</strong><span>${esc(row.created_at || "")}</span></div>
        <b>${row.direction === "debit" ? "-" : "+"}${esc(row.amount_label || "")}</b>
      </div>`);
    customerOrderRows = [
      ...digitalRows.map((row) => ({ ...row, channel: "رقمي", channel_key: "digital" })),
      ...numberRows.map((row) => ({ ...row, channel: "أرقام", channel_key: "numbers" })),
    ];
    renderOrders();
    latestRechargePayload = recharge;
    renderRechargeOptions(recharge);
    renderRechargeRequests(rechargeRequests);
    renderSupportOptions(support);
    renderSupportTickets(support);
  } catch (error) {
    activity.textContent = "تعذر تحميل بيانات الحساب حاليا.";
  }
}

function renderRechargeOptions(payload) {
  const target = $("#recharge-list");
  if (!target) return;
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

function renderRechargeRequests(payload) {
  const target = $("#recharge-requests-list");
  if (!target) return;
  const rows = payload.requests || [];
  setText("#recharge-request-count", rows.length);
  renderRows(target, rows, (row) => `
    <div class="data-row">
      <div>
        <strong>${esc(row.method || "طلب شحن")}</strong>
        <span>${esc(row.created_at || "")}${row.updated_at ? ` · ${esc(row.updated_at)}` : ""}</span>
      </div>
      <div class="stacked-meta">
        <b>${esc(row.status_label || row.status || "")}</b>
        <span>${esc(row.paid_label || row.credits_label || "")}</span>
      </div>
      ${row.delivery_ok ? '<small class="status-pill">وصل للمراجعة</small>' : ""}
    </div>`);
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
    if (result.wallet?.balance_label) {
      setText("#wallet-balance", result.wallet.balance_label);
      setText("#recharge-wallet-balance", result.wallet.balance_label);
    }
    const requests = await api("/api/v1/numbers/recharge/requests?limit=10");
    renderRechargeRequests(requests);
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderSupportOptions(payload) {
  const target = $("#support-list");
  const categorySelect = $("#support-category-select");
  const rows = payload.categories || [];
  const submitEnabled = Boolean(payload.actions?.submit_ticket?.enabled);
  const categoryMeta = {
    numbers: { icon: "📱", description: "مشاكل الطلبات، الأكواد، الأرقام المؤقتة والإيجار." },
    services: { icon: "🎮", description: "طلبات المنتجات الرقمية، الشحن، والأسعار." },
    user_balance: { icon: "💳", description: "شحن الرصيد، الدفعات، والاستردادات." },
  };
  if (categorySelect) {
    categorySelect.innerHTML = rows.map((row) => `<option value="${esc(row.key)}">${esc(row.label || row.key)}</option>`).join("");
    categorySelect.disabled = !submitEnabled || !rows.length;
  }
  const supportForm = $("#support-ticket-form");
  if (supportForm) supportForm.hidden = !submitEnabled || !rows.length;
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
    target.insertAdjacentHTML("beforeend", '<div class="notice support-roadmap">الدعم غير مفعّل حالياً. جرّب مرة أخرى لاحقاً أو تواصل مع الإدارة.</div>');
  }
}

function renderSupportTickets(payload) {
  const target = $("#support-ticket-list");
  if (!target) return;
  const rows = payload.tickets || [];
  renderRows(target, rows, (row) => `
    <div class="data-row">
      <div>
        <strong>#${esc(row.ticket_no || row.id || "")} · ${esc(row.category_label || row.category || "Support")}</strong>
        <span>${esc(row.opened_at || "")}${row.updated_at ? ` · ${esc(row.updated_at)}` : ""}</span>
      </div>
      <div class="stacked-meta">
        <b>${esc(row.status_label || row.status || "")}</b>
        <span>${row.is_open ? "مفتوحة" : "مغلقة"}</span>
      </div>
    </div>`);
}

async function submitSupportTicket(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = $("#support-ticket-message");
  const button = form.querySelector("button[type='submit']");
  message.textContent = "جاري فتح تذكرة الدعم...";
  button.disabled = true;
  try {
    const values = Object.fromEntries(new FormData(form).entries());
    const result = await api("/api/v1/numbers/support/ticket", {
      method: "POST",
      body: JSON.stringify({...values, language: "ar"}),
    });
    message.textContent = result.message || `تم فتح التذكرة #${result.ticket_no || ""}.`;
    form.reset();
    const support = await api("/api/v1/numbers/support");
    renderSupportOptions(support);
    renderSupportTickets(support);
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
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

const ownerShortcutTabs = {
  digital_orders: "orders",
  custom_preorders: "orders",
  numbers_refunds: "orders",
  custom_catalog: "catalog",
  provider_readiness: "providers",
  provider_webhooks: "providers",
  digital_sources: "providers",
  bittopup_watch: "providers",
  recharge_reviews: "finance",
  payment_methods: "finance",
  exchange_rate: "finance",
  numbers_margin: "finance",
  digital_margin: "finance",
  reseller_deposits: "finance",
  bot_subscriptions: "integrations",
  identity_reviews: "users",
  support_inbox: "support",
  support_routing: "system",
  logs_routing: "system",
  provider_alerts: "system",
  broadcast: "system",
  api_keys: "integrations",
  webhooks: "integrations",
};

const ownerGroupTargets = {
  overview: ["owner-metrics", "owner-queues", "owner-sections"],
  finance: ["owner-finance-settings", "owner-payment-methods", "owner-recharge-reviews", "owner-finance-audit", "owner-reseller-deposit-tools", "owner-reseller-management"],
  users: ["owner-user-management", "owner-identity-reviews"],
  support: ["owner-support-tickets"],
  integrations: ["owner-api-tools", "owner-bot-creation-reviews", "owner-bot-tools"],
  providers: ["owner-provider-diagnostics"],
  catalog: ["owner-custom-catalog"],
  system: ["owner-routing-settings", "owner-broadcast-tools", "owner-system-operations"],
  orders: ["owner-digital-orders", "owner-custom-preorders", "owner-refund-reviews"],
};

const ownerLoadingLabels = {
  "owner-metrics": "جاري تحميل مؤشرات الإدارة...",
  "owner-queues": "جاري تحميل طوابير المتابعة...",
  "owner-sections": "جاري تحميل خصائص الإدارة...",
  "owner-finance-settings": "جاري تحميل الإعدادات المالية...",
  "owner-payment-methods": "جاري تحميل طرق الدفع...",
  "owner-recharge-reviews": "جاري تحميل مراجعات الشحن...",
  "owner-finance-audit": "جاري تحميل التدقيق المالي...",
  "owner-reseller-deposit-tools": "جاري تحميل أداة إيداع الوكيل...",
  "owner-reseller-management": "جاري تحميل الوكلاء...",
  "owner-bot-tools": "جاري تحميل أدوات البوتات...",
  "owner-user-management": "جاري تحميل المستخدمين...",
  "owner-identity-reviews": "جاري تحميل مراجعات الهوية...",
  "owner-support-tickets": "جاري تحميل تذاكر الدعم...",
  "owner-api-tools": "جاري تحميل أدوات API...",
  "owner-bot-creation-reviews": "جاري تحميل مراجعات إنشاء البوتات...",
  "owner-provider-diagnostics": "جاري تحميل تشخيص المزودين...",
  "owner-custom-catalog": "جاري تحميل الكتالوغ...",
  "owner-routing-settings": "جاري تحميل إعدادات التوجيه...",
  "owner-broadcast-tools": "جاري تحميل أدوات البث...",
  "owner-system-operations": "جاري تحميل حالة النظام...",
  "owner-digital-orders": "جاري تحميل الطلبات الرقمية...",
  "owner-custom-preorders": "جاري تحميل طلبات preorder...",
  "owner-refund-reviews": "جاري تحميل مراجعات استرداد الأرقام...",
};

function ownerRequestMap() {
  const digitalFilter = $("#owner-digital-filter")?.value || "pending";
  const showResolvedReviews = $("#owner-refunds-resolved")?.checked ? "1" : "0";
  const rechargeFilter = $("#owner-recharge-filter")?.value || "pending";
  const identityFilter = $("#owner-identity-filter")?.value || "pending";
  const supportFilter = $("#owner-support-filter")?.value || "open";
  const sourceFilter = $("#owner-source-filter")?.value || "under_review";
  const auditDays = $("#owner-audit-days")?.value || "30";
  const botReviewFilter = $("#owner-bot-review-filter")?.value || "pending";
  const preorderFilter = $("#owner-preorder-filter")?.value || "active";
  const catalogType = $("#owner-catalog-type")?.value || "custom";
  const ownerAuditQuery = new URLSearchParams({limit: "50"});
  Object.entries(ownerAuditFilters).forEach(([key, value]) => {
    if (value) ownerAuditQuery.set(key, value);
  });
  return {
    overview: {
      dashboard: () => ownerApi("/api/v1/owner/dashboard"),
      queues: () => ownerApi("/api/v1/owner/queues"),
    },
    finance: {
      settings: () => ownerApi("/api/v1/owner/settings"),
      recharge: () => ownerApi(`/api/v1/owner/recharge-reviews?status=${encodeURIComponent(rechargeFilter)}&limit=30`),
      financeAudit: () => ownerApi(`/api/v1/owner/finance/audit?days=${encodeURIComponent(auditDays)}&limit=20`),
      resellers: () => ownerApi(`/api/v1/owner/resellers?q=${encodeURIComponent(ownerResellerQuery)}&limit=30&offset=0`),
    },
    users: {
      users: () => ownerApi(`/api/v1/owner/users?q=${encodeURIComponent(ownerUserQuery)}&limit=20&offset=0`),
      identity: () => ownerApi(`/api/v1/owner/identity-reviews?status=${encodeURIComponent(identityFilter)}&limit=30`),
    },
    support: {
      support: () => ownerApi(`/api/v1/owner/support-tickets?status=${encodeURIComponent(supportFilter)}&limit=30`),
    },
    integrations: {
      apiKeys: () => ownerApi("/api/v1/owner/api-keys?status=all&limit=30"),
      webhooks: () => ownerApi("/api/v1/owner/webhooks?status=all&limit=30"),
      botCreationReviews: () => ownerApi(`/api/v1/owner/bot-creation-reviews?status=${encodeURIComponent(botReviewFilter)}&limit=30`),
      bots: () => ownerApi("/api/v1/owner/bots?status=all&limit=30"),
    },
    providers: {
      providers: () => ownerApi("/api/v1/owner/provider-readiness"),
      providerEvents: () => ownerApi("/api/v1/owner/provider-webhook-events?limit=12"),
      sources: () => ownerApi(`/api/v1/owner/digital-provider-sources?provider=bittopup&status=${encodeURIComponent(sourceFilter)}&limit=30`),
    },
    catalog: {
      catalog: () => ownerApi(`/api/v1/owner/custom-catalog?catalog_type=${encodeURIComponent(catalogType)}${ownerCatalogParentId ? `&parent_id=${encodeURIComponent(ownerCatalogParentId)}` : ""}`),
    },
    system: {
      settings: () => ownerApi("/api/v1/owner/settings"),
      systemStatus: () => ownerApi("/api/v1/owner/system/status"),
      ownerAudit: () => ownerApi(`/api/v1/owner/audit?${ownerAuditQuery.toString()}`),
    },
    orders: {
      digital: () => ownerApi(`/api/v1/owner/digital/orders?status=${encodeURIComponent(digitalFilter)}&limit=30`),
      preorders: () => ownerApi(`/api/v1/owner/custom-preorders?status=${encodeURIComponent(preorderFilter)}&limit=30`),
      refunds: () => ownerApi(`/api/v1/owner/numbers/refund-reviews?include_resolved=${showResolvedReviews}&limit=30`),
    },
  };
}

function tagOwnerGroups() {
  Object.entries(ownerGroupTargets).forEach(([group, ids]) => {
    ids.forEach((id) => {
      const node = document.getElementById(id);
      if (!node) return;
      node.dataset.ownerGroup = group;
      const head = node.previousElementSibling;
      if (head?.classList.contains("section-head")) head.dataset.ownerGroup = group;
    });
  });
}

function applyOwnerTab(tab = "overview", updateRoute = true) {
  activeOwnerTab = ownerGroupTargets[tab] ? tab : "overview";
  tagOwnerGroups();
  document.querySelectorAll("[data-owner-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.ownerTab === activeOwnerTab);
  });
  document.querySelectorAll("[data-owner-group]").forEach((node) => {
    node.hidden = node.dataset.ownerGroup !== activeOwnerTab;
  });
  setPageTitle(ownerTabTitles[activeOwnerTab] || "لوحة الإدارة");
  if (updateRoute) pushRoute(adminRoutes[activeOwnerTab] || "/admin");
}

function openOwnerShortcut(tab = "overview") {
  const nextTab = ownerGroupTargets[tab] ? tab : "overview";
  openPanel("owner", ownerTabTitles[nextTab] || "لوحة الإدارة", { updateRoute: false });
  applyOwnerTab(nextTab);
  loadOwnerDashboard();
}

function setOwnerTabLoading(tab = activeOwnerTab) {
  (ownerGroupTargets[tab] || []).forEach((id) => {
    const node = document.getElementById(id);
    if (!node) return;
    node.classList.add("empty");
    node.setAttribute("aria-busy", "true");
    node.textContent = ownerLoadingLabels[id] || "جاري تحميل بيانات الإدارة...";
  });
}

function clearOwnerBusy(...ids) {
  ids.forEach((id) => document.getElementById(id)?.removeAttribute("aria-busy"));
}

function ownerPagedItems(key, payload, field, append = false) {
  const rows = Array.isArray(payload?.[field]) ? payload[field] : [];
  ownerPagedRows[key] = append ? [...(ownerPagedRows[key] || []), ...rows] : rows;
  return ownerPagedRows[key];
}

function ownerPaginationButton(key, pagination, label = "Load more") {
  if (!pagination?.has_more) return "";
  return `<div class="owner-order-actions"><button class="secondary compact" type="button" data-owner-page="${esc(key)}" data-next-offset="${esc(pagination.next_offset)}">${esc(label)}</button></div>`;
}

function bindOwnerPagination(target) {
  target.querySelectorAll("[data-owner-page]").forEach((button) => button.addEventListener("click", () => loadMoreOwnerList(button)));
}

function setOwnerFormBusy(form, busy) {
  form.querySelectorAll("button").forEach((button) => {
    button.disabled = Boolean(busy);
  });
  form.setAttribute("aria-busy", busy ? "true" : "false");
}

function ownerPagedRequest(key, offset) {
  const params = `limit=30&offset=${encodeURIComponent(offset)}`;
  if (key === "digital") return ownerApi(`/api/v1/owner/digital/orders?status=${encodeURIComponent($("#owner-digital-filter")?.value || "pending")}&${params}`);
  if (key === "preorders") return ownerApi(`/api/v1/owner/custom-preorders?status=${encodeURIComponent($("#owner-preorder-filter")?.value || "active")}&${params}`);
  if (key === "refunds") return ownerApi(`/api/v1/owner/numbers/refund-reviews?include_resolved=${$("#owner-refunds-resolved")?.checked ? "1" : "0"}&${params}`);
  if (key === "recharge") return ownerApi(`/api/v1/owner/recharge-reviews?status=${encodeURIComponent($("#owner-recharge-filter")?.value || "pending")}&${params}`);
  if (key === "identity") return ownerApi(`/api/v1/owner/identity-reviews?status=${encodeURIComponent($("#owner-identity-filter")?.value || "pending")}&${params}`);
  if (key === "support") return ownerApi(`/api/v1/owner/support-tickets?status=${encodeURIComponent($("#owner-support-filter")?.value || "open")}&${params}`);
  if (key === "botCreationReviews") return ownerApi(`/api/v1/owner/bot-creation-reviews?status=${encodeURIComponent($("#owner-bot-review-filter")?.value || "pending")}&${params}`);
  if (key === "bots") return ownerApi(`/api/v1/owner/bots?status=all&${params}`);
  throw new Error("Unsupported owner list.");
}

async function loadMoreOwnerList(button) {
  button.disabled = true;
  try {
    const key = button.dataset.ownerPage;
    const payload = await ownerPagedRequest(key, Number(button.dataset.nextOffset || 0));
    const renderers = {
      digital: renderOwnerDigitalOrders,
      preorders: renderOwnerCustomPreorders,
      refunds: renderOwnerRefundReviews,
      recharge: renderOwnerRechargeReviews,
      identity: renderOwnerIdentityReviews,
      support: renderOwnerSupportTickets,
      botCreationReviews: renderOwnerBotCreationReviews,
      bots: renderOwnerBotTools,
    };
    renderers[key](payload, true);
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

async function loadOwnerDashboardIsolated() {
  const loadId = ++ownerDashboardLoadId;
  const loadTab = activeOwnerTab;
  const metricsTarget = $("#owner-metrics");
  const queuesTarget = $("#owner-queues");
  const sectionsTarget = $("#owner-sections");
  const message = $("#owner-message");
  const fail = (selector, text) => {
    const target = typeof selector === "string" ? $(selector) : selector;
    if (!target) return;
    target.classList?.add("empty");
    target.textContent = text;
  };
  const requests = ownerRequestMap()[activeOwnerTab] || ownerRequestMap().overview;
  setOwnerTabLoading(activeOwnerTab);
  const requested = (key) => Object.prototype.hasOwnProperty.call(requests, key);
  const settled = await Promise.allSettled(Object.entries(requests).map(async ([key, factory]) => [key, await factory()]));
  if (loadId !== ownerDashboardLoadId || loadTab !== activeOwnerTab) return;
  const data = {};
  const failures = [];
  settled.forEach((result) => {
    if (result.status === "fulfilled") data[result.value[0]] = result.value[1];
    else failures.push(result.reason?.message || "request failed");
  });
  if (requested("dashboard") && data.dashboard) {
    clearOwnerBusy("owner-metrics", "owner-sections");
    const metrics = Object.entries(data.dashboard.metrics || {});
    metricsTarget.classList.toggle("empty", !metrics.length);
    metricsTarget.innerHTML = metrics.map(([key, value]) => `
      <div class="owner-metric">
        <span>${esc(ownerMetricLabels[key] || key)}</span>
        <strong>${esc(value)}</strong>
      </div>`).join("");
    const sections = data.dashboard.sections || [];
    sectionsTarget.classList.toggle("empty", !sections.length);
    sectionsTarget.innerHTML = sections.map((section) => `
      <section class="owner-section">
        <h4>${esc(section.title || section.key)}</h4>
        <div class="owner-action-list">
          ${(section.items || []).map((item) => {
            const shortcutTab = ownerShortcutTabs[item.key] || ownerShortcutTabs[section.key] || "";
            const tag = shortcutTab ? "button" : "div";
            const shortcutAttrs = shortcutTab ? `type="button" data-owner-shortcut="${esc(shortcutTab)}"` : "";
            return `
            <${tag} class="owner-action-row ${shortcutTab ? "owner-shortcut-row" : ""}" ${shortcutAttrs}>
              <div><strong>${esc(item.title || item.key)}</strong><span>${esc(item.endpoint || "Website action")}</span></div>
              <b data-owner-status="${esc(item.status || "")}">${esc(ownerStatusLabels[item.status] || item.status)}</b>
            </${tag}>`;
          }).join("")}
        </div>
      </section>`).join("");
    sectionsTarget.querySelectorAll("[data-owner-shortcut]").forEach((button) => {
      button.addEventListener("click", () => openOwnerShortcut(button.dataset.ownerShortcut || "overview"));
    });
  } else if (requested("dashboard")) {
    clearOwnerBusy("owner-metrics", "owner-sections");
    fail(metricsTarget, "تعذر تحميل مؤشرات المالك.");
    fail(sectionsTarget, "تعذر تحميل خصائص الإدارة.");
  }
  if (requested("queues") && data.queues) {
    clearOwnerBusy("owner-queues");
    const queues = Object.entries(data.queues.queues || {});
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
  } else if (requested("queues")) {
    clearOwnerBusy("owner-queues");
    fail(queuesTarget, "تعذر تحميل طوابير المتابعة.");
  }
  if (requested("digital")) { clearOwnerBusy("owner-digital-orders"); data.digital ? renderOwnerDigitalOrders(data.digital) : fail("#owner-digital-orders", "تعذر تحميل الطلبات الرقمية."); }
  if (requested("preorders")) { clearOwnerBusy("owner-custom-preorders"); data.preorders ? renderOwnerCustomPreorders(data.preorders) : fail("#owner-custom-preorders", "Could not load custom preorders."); }
  if (requested("catalog")) { clearOwnerBusy("owner-custom-catalog"); data.catalog ? renderOwnerCustomCatalog(data.catalog) : fail("#owner-custom-catalog", "Could not load custom services catalog."); }
  if (requested("refunds")) { clearOwnerBusy("owner-refund-reviews"); data.refunds ? renderOwnerRefundReviews(data.refunds) : fail("#owner-refund-reviews", "تعذر تحميل مراجعات الأرقام."); }
  if (requested("settings")) { clearOwnerBusy("owner-finance-settings", "owner-routing-settings", "owner-broadcast-tools", "owner-payment-methods", "owner-reseller-deposit-tools"); data.settings ? renderOwnerSettings(data.settings) : fail("#owner-finance-settings", "تعذر تحميل الإعدادات المالية."); }
  if (requested("settings") && !data.settings) {
    fail("#owner-routing-settings", "تعذر تحميل إعدادات التوجيه.");
    fail("#owner-broadcast-tools", "تعذر تحميل أدوات البث.");
    fail("#owner-payment-methods", "تعذر تحميل طرق الدفع.");
    fail("#owner-reseller-deposit-tools", "تعذر تحميل أداة إيداع الوكيل.");
  }
  if (requested("recharge")) { clearOwnerBusy("owner-recharge-reviews"); data.recharge ? renderOwnerRechargeReviews(data.recharge) : fail("#owner-recharge-reviews", "تعذر تحميل مراجعات الشحن."); }
  if (requested("financeAudit")) { clearOwnerBusy("owner-finance-audit"); data.financeAudit ? renderOwnerFinanceAudit(data.financeAudit.audit || {}) : fail("#owner-finance-audit", "تعذر تحميل التدقيق المالي."); }
  if (requested("systemStatus") || requested("ownerAudit")) {
    clearOwnerBusy("owner-system-operations");
    data.systemStatus && data.ownerAudit ? renderOwnerSystemOperations(data.systemStatus.system || {}, data.ownerAudit) : fail("#owner-system-operations", "تعذر تحميل عمليات النظام.");
  }
  if (requested("resellers")) { clearOwnerBusy("owner-reseller-management"); data.resellers ? renderOwnerResellerManagement(data.resellers) : fail("#owner-reseller-management", "تعذر تحميل الوكلاء."); }
  if (requested("users")) { clearOwnerBusy("owner-user-management"); data.users ? renderOwnerUserManagement(data.users) : fail("#owner-user-management", "تعذر تحميل المستخدمين."); }
  if (requested("identity")) { clearOwnerBusy("owner-identity-reviews"); data.identity ? renderOwnerIdentityReviews(data.identity) : fail("#owner-identity-reviews", "تعذر تحميل مراجعات الهوية."); }
  if (requested("support")) { clearOwnerBusy("owner-support-tickets"); data.support ? renderOwnerSupportTickets(data.support) : fail("#owner-support-tickets", "تعذر تحميل تذاكر الدعم."); }
  if (requested("apiKeys") || requested("webhooks")) { clearOwnerBusy("owner-api-tools"); data.apiKeys && data.webhooks ? renderOwnerApiTools(data.apiKeys, data.webhooks) : fail("#owner-api-tools", "تعذر تحميل أدوات API."); }
  if (requested("botCreationReviews")) { clearOwnerBusy("owner-bot-creation-reviews"); data.botCreationReviews ? renderOwnerBotCreationReviews(data.botCreationReviews) : fail("#owner-bot-creation-reviews", "تعذر تحميل مراجعات إنشاء البوتات."); }
  if (requested("providers") || requested("providerEvents") || requested("sources")) {
    clearOwnerBusy("owner-provider-diagnostics");
    data.providers && data.providerEvents && data.sources
      ? renderOwnerProviderDiagnostics(data.providers, data.providerEvents, data.sources)
      : fail("#owner-provider-diagnostics", "تعذر تحميل تشخيص المزودين.");
  }
  if (requested("bots")) { clearOwnerBusy("owner-bot-tools"); data.bots ? renderOwnerBotTools(data.bots) : fail("#owner-bot-tools", "تعذر تحميل أدوات البوتات."); }
  message.textContent = failures.length ? `تعذر تحميل ${failures.length} قسم/أقسام. آخر خطأ: ${failures[0]}` : "";
  applyOwnerTab(activeOwnerTab, false);
}

async function loadOwnerDashboard() {
  const message = $("#owner-message");
  if (!currentAccount?.is_owner) return;
  message.textContent = "";
  return loadOwnerDashboardIsolated();
}

function renderOwnerApiTools(keysPayload, webhooksPayload, appendKey = "") {
  const keyScopes = keysPayload.scopes || [];
  const webhookEvents = webhooksPayload.events || [];
  const keys = ownerPagedItems("apiKeys", keysPayload, "keys", appendKey === "apiKeys");
  const hooks = ownerPagedItems("webhooks", webhooksPayload, "webhooks", appendKey === "webhooks");
  ownerIntegrationPayloads = {
    apiKeys: {...keysPayload, keys, scopes: keyScopes},
    webhooks: {...webhooksPayload, webhooks: hooks, events: webhookEvents},
  };
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
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("apiKeys", keysPayload.pagination, "Load more API keys"));
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("webhooks", webhooksPayload.pagination, "Load more webhooks"));
  target.querySelectorAll("[data-owner-page='apiKeys'], [data-owner-page='webhooks']").forEach((button) => button.addEventListener("click", () => loadMoreOwnerIntegration(button)));
}

async function loadMoreOwnerIntegration(button) {
  button.disabled = true;
  try {
    const key = button.dataset.ownerPage;
    const offset = Number(button.dataset.nextOffset || 0);
    const path = key === "apiKeys" ? "/api/v1/owner/api-keys" : "/api/v1/owner/webhooks";
    const payload = await api(`${path}?status=all&limit=30&offset=${encodeURIComponent(offset)}`);
    renderOwnerApiTools(
      key === "apiKeys" ? payload : ownerIntegrationPayloads.apiKeys,
      key === "webhooks" ? payload : ownerIntegrationPayloads.webhooks,
      key,
    );
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

function selectedValues(select) {
  return Array.from(select?.selectedOptions || []).map((option) => option.value);
}

async function createOwnerApiKey(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  body.scopes = selectedValues(form.elements.scopes);
  setOwnerFormBusy(form, true);
  try {
    const result = await ownerApi("/api/v1/owner/api-keys", {method: "POST", body: JSON.stringify(body)});
    const box = $("#owner-api-secret");
    box.hidden = false;
    box.textContent = `API key يظهر مرة واحدة فقط: ${result.api_key}`;
    setText("#owner-message", "تم إنشاء المفتاح. احفظه الآن لأنه لن يظهر مرة ثانية.");
  } catch (error) { setText("#owner-message", error.message); }
  finally { setOwnerFormBusy(form, false); }
}

async function createOwnerWebhook(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  body.events = selectedValues(form.elements.events);
  setOwnerFormBusy(form, true);
  try {
    const result = await ownerApi("/api/v1/owner/webhooks", {method: "POST", body: JSON.stringify(body)});
    const box = $("#owner-webhook-secret");
    box.hidden = false;
    box.textContent = `Webhook secret يظهر مرة واحدة فقط: ${result.secret}`;
    setText("#owner-message", "تم إنشاء webhook. احفظ السر الآن لأنه لن يظهر مرة ثانية.");
  } catch (error) { setText("#owner-message", error.message); }
  finally { setOwnerFormBusy(form, false); }
}

async function revokeOwnerApiKey(button) {
  if (!window.confirm("إلغاء هذا المفتاح؟")) return;
  await ownerApi(`/api/v1/owner/api-keys/${encodeURIComponent(button.dataset.ownerApiKey)}/revoke`, {method: "POST"});
  await loadOwnerDashboard();
}

async function revokeOwnerWebhook(button) {
  if (!window.confirm("إلغاء هذا webhook؟")) return;
  await ownerApi(`/api/v1/owner/webhooks/${encodeURIComponent(button.dataset.ownerWebhook)}/revoke`, {method: "POST"});
  await loadOwnerDashboard();
}

function renderOwnerProviderDiagnostics(providersPayload, eventsPayload, sourcesPayload = {}, appendKey = "") {
  const target = $("#owner-provider-diagnostics");
  const providers = providersPayload.providers || [];
  const events = ownerPagedItems("providerEvents", eventsPayload, "events", appendKey === "providerEvents");
  const sources = ownerPagedItems("providerSources", sourcesPayload, "sources", appendKey === "providerSources");
  const runs = sourcesPayload.runs || [];
  ownerProviderPayloads = {
    providers: providersPayload,
    events: {...eventsPayload, events},
    sources: {...sourcesPayload, sources, runs},
  };
  target.classList.remove("empty");
  target.innerHTML = `
    <article class="owner-review-card">
      <h4>جاهزية المزودين</h4>
      ${providers.map((provider) => `<div class="owner-action-row"><div><strong>${esc(provider.provider)}</strong><span>${esc(provider.reason || "")}</span></div><b>${esc(provider.status)}</b></div>`).join("") || '<div class="notice">لا توجد بيانات جاهزية.</div>'}
    </article>
    <article class="owner-review-card">
      <h4>آخر provider webhooks</h4>
      ${events.map((event) => `<div class="owner-action-row"><div><strong>${esc(event.provider)} · ${esc(event.event_type)}</strong><span>${esc(event.provider_order_id)} · ${esc(event.reason || event.created_at || "")}</span></div><b>${esc(event.status)}</b><button class="secondary compact" data-provider-event="${esc(event.id)}">Replay</button></div>`).join("") || '<div class="notice">لا توجد أحداث webhook حديثة.</div>'}
    </article>
    <article class="owner-review-card">
      <div class="owner-order-head"><div><h4>BitTopup price watch</h4><span>${runs.length ? `آخر تشغيل: ${esc(runs[0].status)} · ${esc(runs[0].finished_at || runs[0].started_at || "")}` : "لا يوجد تشغيل مسجل"}</span></div><button class="secondary compact" id="owner-bittopup-scan" type="button">تشغيل Scan</button></div>
      ${runs.length ? `<div class="owner-order-meta">${runs.slice(0, 3).map((run) => `<span>${esc(run.status)} · pages ${esc(run.stats?.pages_checked || 0)} · offers ${esc(run.stats?.offers_seen || 0)}</span>`).join("")}</div>` : ""}
      ${sources.length ? sources.map((source) => `<div class="owner-action-row owner-source-row">
        <div>
          <strong>${esc(source.product_name || source.source_ref)} · ${esc(source.denomination_name)}</strong>
          <span>${esc(source.status)} · ${esc(source.reason || "ok")} · observed $${esc(source.observed_price)} · active $${esc(source.active_price)} · ${esc(source.compare_key || "no compare key")}</span>
          ${safeExternalUrl(source.source_url) ? `<a href="${esc(safeExternalUrl(source.source_url))}" target="_blank" rel="noopener noreferrer">${esc(source.source_url)}</a>` : ""}
        </div>
        <div class="owner-order-actions">
          <button class="secondary compact" data-owner-source="${esc(source.id)}" data-source-action="approve">Approve</button>
          <button class="danger compact" data-owner-source="${esc(source.id)}" data-source-action="disable">Disable</button>
        </div>
      </div>`).join("") : '<div class="notice">لا توجد مصادر ضمن هذا الفلتر.</div>'}
    </article>`;
  target.querySelectorAll("[data-provider-event]").forEach((button) => button.addEventListener("click", () => replayOwnerProviderEvent(button)));
  target.querySelector("#owner-bittopup-scan")?.addEventListener("click", runOwnerBittopupScan);
  target.querySelectorAll("[data-owner-source]").forEach((button) => button.addEventListener("click", () => runOwnerSourceAction(button)));
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("providerEvents", eventsPayload.pagination, "Load more provider webhook events"));
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("providerSources", sourcesPayload.pagination, "Load more provider sources"));
  target.querySelectorAll("[data-owner-page='providerEvents'], [data-owner-page='providerSources']").forEach((button) => button.addEventListener("click", () => loadMoreOwnerProviderDiagnostics(button)));
}

async function loadMoreOwnerProviderDiagnostics(button) {
  button.disabled = true;
  try {
    const key = button.dataset.ownerPage;
    const offset = Number(button.dataset.nextOffset || 0);
    const payload = key === "providerEvents"
      ? await ownerApi(`/api/v1/owner/provider-webhook-events?limit=30&offset=${encodeURIComponent(offset)}`)
      : await ownerApi(`/api/v1/owner/digital-provider-sources?provider=bittopup&status=${encodeURIComponent($("#owner-source-filter")?.value || "under_review")}&limit=30&offset=${encodeURIComponent(offset)}`);
    renderOwnerProviderDiagnostics(
      ownerProviderPayloads.providers,
      key === "providerEvents" ? payload : ownerProviderPayloads.events,
      key === "providerSources" ? payload : ownerProviderPayloads.sources,
      key,
    );
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

async function replayOwnerProviderEvent(button) {
  if (!window.confirm("إعادة تشغيل هذا الحدث قد يغير حالة الطلب المرتبط. متابعة؟")) return;
  try {
    await ownerApi(`/api/v1/owner/provider-webhook-events/${encodeURIComponent(button.dataset.providerEvent)}/replay`, {method: "POST"});
    setText("#owner-message", "تم تنفيذ replay للحدث.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

async function runOwnerBittopupScan() {
  if (!window.confirm("تشغيل BitTopup scan قد يستغرق وقتا ويحدّث مصادر الأسعار. متابعة؟")) return;
  try {
    setText("#owner-message", "جاري تشغيل BitTopup scan...");
    const result = await ownerApi("/api/v1/owner/digital-provider-sources/scan", {method: "POST", body: JSON.stringify({})});
    setText("#owner-message", `انتهى scan: ${result.scan?.status || "done"}.`);
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

async function runOwnerSourceAction(button) {
  const action = button.dataset.sourceAction || "";
  if (!window.confirm(`${action} لهذا المصدر؟`)) return;
  try {
    await ownerApi(`/api/v1/owner/digital-provider-sources/${encodeURIComponent(button.dataset.ownerSource)}/action`, {
      method: "POST",
      body: JSON.stringify({action}),
    });
    setText("#owner-message", "تم تحديث مصدر المنتج.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

function renderOwnerBotTools(payload, append = false) {
  const target = $("#owner-bot-tools");
  const bots = ownerPagedItems("bots", payload, "bots", append);
  target.classList.remove("empty");
  target.innerHTML = `
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
  target.querySelectorAll("[data-owner-bot]").forEach((form) => form.addEventListener("submit", runOwnerBotSubscriptionAction));
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("bots", payload.pagination, "Load more bots"));
  bindOwnerPagination(target);
}

function renderOwnerBroadcastTools(routing = {}) {
  const target = $("#owner-broadcast-tools");
  if (!target) return;
  target.classList.remove("empty");
  target.innerHTML = `
    <article class="owner-review-card">
      <div class="owner-order-head">
        <div><h4>بث عبر بوت المنصة</h4><span>${esc(routingLabel(routing.owner_notifications))}</span></div>
      </div>
      <form class="owner-review-form" id="owner-broadcast-form">
        <label><span>Chat ID</span><input name="chat_id" required inputmode="numeric" placeholder="-100..."></label>
        <label><span>Topic ID</span><input name="message_thread_id" inputmode="numeric" placeholder="اختياري"></label>
        <label><span>نص البث</span><textarea name="text" required minlength="2" maxlength="3500" rows="3" placeholder="اكتب الرسالة التي ستصل للقناة أو المجموعة"></textarea></label>
        <div class="owner-order-actions"><button class="primary compact" type="submit">إرسال البث</button></div>
      </form>
    </article>`;
  $("#owner-broadcast-form")?.addEventListener("submit", sendOwnerBroadcastForm);
}

function renderOwnerResellerDepositTools() {
  const target = $("#owner-reseller-deposit-tools");
  if (!target) return;
  target.classList.remove("empty");
  target.innerHTML = `
    <article class="owner-review-card">
      <h4>إيداع رصيد وكيل</h4>
      <form class="owner-review-form" id="owner-reseller-deposit-form">
        <label><span>Reseller ID</span><input name="reseller_id" required inputmode="numeric"></label>
        <label><span>المبلغ</span><input name="amount" required type="number" min="0.01" max="10000000" step="0.01"></label>
        <label><span>ملاحظة</span><input name="note" maxlength="300" placeholder="اختياري"></label>
        <div class="owner-order-actions"><button class="primary compact" type="submit">إضافة الرصيد</button></div>
      </form>
    </article>`;
  $("#owner-reseller-deposit-form")?.addEventListener("submit", createOwnerResellerDeposit);
}

async function sendOwnerBroadcastForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!window.confirm("سيتم إرسال هذه الرسالة فعليا عبر بوت المنصة. متابعة؟")) return;
  const body = Object.fromEntries(new FormData(form).entries());
  setOwnerFormBusy(form, true);
  try {
    await ownerApi("/api/v1/owner/broadcast", {method: "POST", body: JSON.stringify(body)});
    setText("#owner-message", "تم إرسال البث.");
    form.reset();
  } catch (error) { setText("#owner-message", error.message); }
  finally { setOwnerFormBusy(form, false); }
}

async function createOwnerResellerDeposit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  if (!window.confirm(`سيتم إضافة ${body.amount || 0} إلى محفظة الوكيل ${body.reseller_id || ""}. متابعة؟`)) return;
  setOwnerFormBusy(form, true);
  try {
    await ownerApi("/api/v1/owner/reseller-deposits", {method: "POST", body: JSON.stringify(body)});
    setText("#owner-message", "تم إضافة رصيد الوكيل.");
    form.reset();
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { setOwnerFormBusy(form, false); }
}

async function runOwnerBotSubscriptionAction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const action = event.submitter?.value || "sync";
  const body = Object.fromEntries(new FormData(form).entries());
  body.action = action;
  if (action === "activate" && !window.confirm("سيتم تمديد اشتراك هذا البوت. متابعة؟")) return;
  try {
    await ownerApi(`/api/v1/owner/bots/${encodeURIComponent(form.dataset.ownerBot)}/subscription/action`, {method: "POST", body: JSON.stringify(body)});
    setText("#owner-message", "تم تحديث اشتراك البوت.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

function renderOwnerFinanceAudit(audit) {
  const target = $("#owner-finance-audit");
  const rows = [
    ...(audit.negative_wallets || []).map((row) => ({kind: "Negative wallet", detail: `${row.owner_type}:${row.owner_id} / ${row.wallet_type}`, amount: row.balance})),
    ...(audit.orders_missing_ledger || []).map((row) => ({kind: "Order missing ledger", detail: `${row.order_id} / ${row.service_type}`, amount: row.status})),
    ...(audit.accepted_recharges_without_ledger || []).map((row) => ({kind: "Recharge missing ledger", detail: `${row.request_id} / ${row.wallet_type}`, amount: row.amount})),
  ];
  const totals = [
    ["Negative wallets", audit.negative_wallets_count || 0],
    ["Orders missing ledger", audit.orders_missing_ledger_count || 0],
    ["Accepted recharges without ledger", audit.accepted_recharges_without_ledger_count || 0],
  ];
  target.classList.toggle("empty", false);
  target.innerHTML = `
    <div class="owner-metrics compact">
      ${totals.map(([label, value]) => `<div class="owner-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("")}
    </div>
    ${rows.length ? rows.map((row) => `
      <div class="owner-action-row"><div><strong>${esc(row.kind)}</strong><span>${esc(row.detail)}</span></div><b>${esc(row.amount)}</b></div>
    `).join("") : '<div class="notice">No financial anomalies were found in this window.</div>'}
  `;
}

function renderOwnerSystemOperations(system, auditPayload, append = false) {
  const target = $("#owner-system-operations");
  const events = ownerPagedItems("ownerAudit", auditPayload, "events", append);
  const filters = auditPayload.filters || ownerAuditFilters;
  ownerSystemStatusPayload = system;
  const routing = system.routing || {};
  const checks = [
    ["MongoDB", system.mongo?.status || "unknown"],
    ["Website", system.website_enabled ? "enabled" : "disabled"],
    ["Active bots", system.active_bots || 0],
    ["Inactive bots", system.inactive_bots || 0],
    ["Pending orders", system.pending_orders || 0],
    ["Pending recharges", system.pending_recharges || 0],
    ["Ready providers", `${system.provider_readiness?.ready || 0}/${system.provider_readiness?.total || 0}`],
    ["Support routing", `${routing.support_bound || 0}/${routing.support_total || 4}`],
  ];
  target.classList.remove("empty");
  target.innerHTML = `
    <article class="owner-review-card">
      <div class="owner-order-head"><div><h4>System status</h4><span>Bot version ${esc(system.bot_version || "-")}</span></div><button id="owner-test-log" class="secondary compact" type="button">Send test log</button></div>
      <div class="owner-metrics compact">${checks.map(([label, value]) => `<div class="owner-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("")}</div>
      <div class="owner-order-meta"><span>Logs: ${routing.logs_bound ? "bound" : "not bound"}</span><span>Provider alerts: ${routing.provider_alerts_enabled ? "enabled" : "disabled"}</span><span>Alerts target: ${routing.provider_alerts_bound ? "bound" : "not bound"}</span></div>
    </article>
    <article class="owner-review-card">
      <h4>Owner audit trail</h4>
      <form class="owner-review-form" id="owner-audit-filter-form">
        <label><span>Search actor or target</span><input name="q" value="${esc(filters.q || "")}" placeholder="email, id, or action"></label>
        <label><span>Action</span><input name="action" value="${esc(filters.action || "")}" placeholder="recharge_review.accept"></label>
        <label><span>Target type</span><input name="target_type" value="${esc(filters.target_type || "")}" placeholder="recharge_request"></label>
        <div class="owner-order-actions"><button class="secondary compact" type="submit">Filter audit</button><button class="secondary compact" id="owner-audit-filter-reset" type="button">Reset</button></div>
      </form>
      ${events.length ? events.map((event) => `<div class="owner-action-row"><div><strong>${esc(event.action)}</strong><span>${esc(event.actor_email || event.actor_id)} · ${esc(event.target_type)} ${esc(event.target_id)} · ${esc(event.created_at)}</span></div></div>`).join("") : '<div class="notice">No website owner actions recorded yet.</div>'}
    </article>
  `;
  $("#owner-test-log")?.addEventListener("click", sendOwnerTestLog);
  $("#owner-audit-filter-form")?.addEventListener("submit", applyOwnerAuditFilters);
  $("#owner-audit-filter-reset")?.addEventListener("click", resetOwnerAuditFilters);
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("ownerAudit", auditPayload.pagination, "Load more audit events"));
  target.querySelector("[data-owner-page='ownerAudit']")?.addEventListener("click", loadMoreOwnerAudit);
}

async function loadMoreOwnerAudit(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const query = new URLSearchParams({limit: "50", offset: String(button.dataset.nextOffset || 0)});
    Object.entries(ownerAuditFilters).forEach(([key, value]) => {
      if (value) query.set(key, value);
    });
    const payload = await ownerApi(`/api/v1/owner/audit?${query.toString()}`);
    renderOwnerSystemOperations(ownerSystemStatusPayload, payload, true);
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

async function applyOwnerAuditFilters(event) {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget).entries());
  ownerAuditFilters = {
    q: String(values.q || "").trim(),
    action: String(values.action || "").trim(),
    target_type: String(values.target_type || "").trim(),
  };
  await loadOwnerDashboard();
}

async function resetOwnerAuditFilters() {
  ownerAuditFilters = {q: "", action: "", target_type: ""};
  await loadOwnerDashboard();
}

async function sendOwnerTestLog() {
  try {
    await ownerApi("/api/v1/owner/system/test-log", {method: "POST", body: JSON.stringify({})});
    setText("#owner-message", "Test log was emitted to the configured logs target.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

function renderOwnerResellerManagement(payload, append = false) {
  const target = $("#owner-reseller-management");
  const rows = Array.isArray(payload?.resellers) ? payload.resellers : [];
  ownerResellerRows = append ? [...ownerResellerRows, ...rows] : rows;
  const pagination = payload?.pagination || {};
  target.classList.remove("empty");
  target.innerHTML = `
    <form class="owner-review-form" id="owner-reseller-search-form">
      <label><span>Search reseller</span><input id="owner-reseller-search-input" name="q" value="${esc(ownerResellerQuery)}" placeholder="reseller id, bot id, username"></label>
      <button class="secondary compact" type="submit">Search</button>
    </form>
    <div id="owner-reseller-detail" class="notice" hidden></div>
    <div class="owner-action-list">
      ${ownerResellerRows.length ? ownerResellerRows.map((row) => `
        <div class="owner-action-row">
          <div><strong>${esc(row.username ? `@${row.username}` : `Reseller ${row.reseller_id}`)}</strong><span>${esc(row.reseller_id)} · bots ${esc(row.active_bots_count)}/${esc(row.bots_count)}</span></div>
          <div class="owner-order-actions"><b>Main ${esc(row.main_balance)}$ · Earnings ${esc(row.earnings_balance)}$</b><button class="secondary compact" data-owner-reseller-detail="${esc(row.reseller_id)}">Details</button></div>
        </div>
      `).join("") : '<div class="notice">No resellers found.</div>'}
    </div>
    ${pagination.has_more ? `<div class="owner-order-actions"><button class="secondary compact" id="owner-resellers-load-more" data-next-offset="${esc(pagination.next_offset)}" type="button">Load more resellers</button></div>` : ""}
  `;
  $("#owner-reseller-search-form")?.addEventListener("submit", searchOwnerResellers);
  $("#owner-resellers-load-more")?.addEventListener("click", loadMoreOwnerResellers);
  target.querySelectorAll("[data-owner-reseller-detail]").forEach((button) => button.addEventListener("click", () => loadOwnerResellerDetail(button.dataset.ownerResellerDetail)));
}

async function searchOwnerResellers(event) {
  event.preventDefault();
  ownerResellerQuery = String($("#owner-reseller-search-input")?.value || "").trim();
  try {
    const payload = await ownerApi(`/api/v1/owner/resellers?q=${encodeURIComponent(ownerResellerQuery)}&limit=30&offset=0`);
    renderOwnerResellerManagement(payload);
  } catch (error) { setText("#owner-message", error.message); }
}

async function loadMoreOwnerResellers(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const offset = Number(button.dataset.nextOffset || 0);
    const payload = await ownerApi(`/api/v1/owner/resellers?q=${encodeURIComponent(ownerResellerQuery)}&limit=30&offset=${encodeURIComponent(offset)}`);
    renderOwnerResellerManagement(payload, true);
  } catch (error) { setText("#owner-message", error.message); }
  finally { button.disabled = false; }
}

async function loadOwnerResellerDetail(resellerId) {
  try {
    const payload = await ownerApi(`/api/v1/owner/resellers/${encodeURIComponent(resellerId)}`);
    const row = payload.reseller || {};
    const target = $("#owner-reseller-detail");
    target.hidden = false;
    target.innerHTML = `
      <strong>${esc(row.username ? `@${row.username}` : `Reseller ${row.reseller_id}`)}</strong>
      <div class="owner-order-meta">${(row.wallets || []).map((wallet) => `<span>${esc(wallet.wallet_type)}: ${esc(wallet.balance)}$</span>`).join("")}<span>Bots: ${esc((row.bots || []).length)}</span><span>Banned: ${row.banned ? "yes" : "no"}</span></div>
      <h4>Bots</h4>
      ${(row.bots || []).map((bot) => `<div class="owner-queue-row"><div><strong>${esc(bot.username || bot.bot_id)}</strong><span>${esc(bot.subscription?.status || "-")} · ${esc(bot.subscription_channel || "no channel")}</span></div><b>${bot.active ? "active" : "inactive"}</b></div>`).join("") || '<div>No bots.</div>'}
      <h4>Recent ledger</h4>
      ${(row.ledger || []).map((entry) => `<div class="owner-queue-row"><div><strong>${esc(entry.reason)}</strong><span>${esc(entry.created_at)}</span></div><b>${esc(entry.direction)} ${esc(entry.amount)}</b></div>`).join("") || '<div>No ledger entries.</div>'}
    `;
  } catch (error) { setText("#owner-message", error.message); }
}

function renderOwnerUserManagement(payload, append = false) {
  const target = $("#owner-user-management");
  const rows = Array.isArray(payload?.users) ? payload.users : [];
  ownerUserRows = append ? [...ownerUserRows, ...rows] : rows;
  const pagination = payload?.pagination || {};
  target.classList.toggle("empty", false);
  target.innerHTML = `
    <form class="owner-review-form" id="owner-user-search-form">
      <label><span>Search</span><input id="owner-user-search-input" name="q" value="${esc(ownerUserQuery)}" placeholder="email, customer id, telegram id"></label>
      <button class="secondary compact" type="submit">Search</button>
    </form>
    <div id="owner-user-detail" class="notice" hidden></div>
    <div class="owner-action-list">
      ${ownerUserRows.length ? ownerUserRows.map((row) => `
        <div class="owner-action-row">
          <div>
            <strong>${esc(row.email || row.username || row.customer_id)}</strong>
            <span>ID ${esc(row.customer_id)} · ${row.email_verified ? "verified" : "unverified"} · ${row.telegram_id ? `TG ${esc(row.telegram_id)}` : "no telegram"}</span>
          </div>
          <div class="owner-order-actions">
            <b>${esc(row.balance || 0)}$</b>
            <button class="secondary compact" data-owner-user-detail="${esc(row.customer_id)}">Details</button>
            <button class="${row.banned ? "secondary" : "danger"} compact" data-owner-user-action="${esc(row.customer_id)}" data-action="${row.banned ? "unban" : "ban"}">${row.banned ? "Unban" : "Ban"}</button>
          </div>
        </div>
      `).join("") : '<div class="notice">No users found.</div>'}
    </div>
    ${pagination.has_more ? `<div class="owner-order-actions"><button class="secondary compact" id="owner-users-load-more" data-next-offset="${esc(pagination.next_offset)}" type="button">Load more users</button></div>` : ""}
  `;
  $("#owner-user-search-form")?.addEventListener("submit", searchOwnerUsers);
  $("#owner-users-load-more")?.addEventListener("click", loadMoreOwnerUsers);
  target.querySelectorAll("[data-owner-user-detail]").forEach((button) => button.addEventListener("click", () => loadOwnerUserDetail(button.dataset.ownerUserDetail)));
  target.querySelectorAll("[data-owner-user-action]").forEach((button) => button.addEventListener("click", () => runOwnerUserAction(button)));
}

async function searchOwnerUsers(event) {
  event.preventDefault();
  ownerUserQuery = String($("#owner-user-search-input")?.value || "").trim();
  try {
    const payload = await ownerApi(`/api/v1/owner/users?q=${encodeURIComponent(ownerUserQuery)}&limit=20&offset=0`);
    renderOwnerUserManagement(payload);
  } catch (error) { setText("#owner-message", error.message); }
}

async function loadMoreOwnerUsers(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const offset = Number(button.dataset.nextOffset || 0);
    const payload = await ownerApi(`/api/v1/owner/users?q=${encodeURIComponent(ownerUserQuery)}&limit=20&offset=${encodeURIComponent(offset)}`);
    renderOwnerUserManagement(payload, true);
  } catch (error) { setText("#owner-message", error.message); }
  finally { button.disabled = false; }
}

async function loadOwnerUserDetail(customerId) {
  try {
    const payload = await ownerApi(`/api/v1/owner/users/${encodeURIComponent(customerId)}`);
    const target = $("#owner-user-detail");
    const user = payload.user || {};
    target.hidden = false;
    target.innerHTML = `
      <strong>${esc(user.email || user.customer_id)}</strong>
      <div class="owner-order-meta"><span>Balance: ${esc(payload.wallet?.balance || 0)}$</span><span>Status: ${esc(user.status)}</span><span>Identity: ${esc(user.identity_status)}</span><span>Banned: ${user.banned ? "yes" : "no"}</span></div>
      <h4>Recent ledger</h4>
      ${(payload.ledger || []).map((row) => `<div class="owner-queue-row"><div><strong>${esc(row.reason)}</strong><span>${esc(row.created_at)}</span></div><b>${esc(row.direction)} ${esc(row.amount)}</b></div>`).join("") || '<div>No ledger entries.</div>'}
      <h4>Recent orders</h4>
      ${(payload.orders || []).map((row) => `<div class="owner-queue-row"><div><strong>${esc(row.title || row.service_type)}</strong><span>${esc(row.id)}</span></div><b>${esc(row.status)}</b></div>`).join("") || '<div>No recent orders.</div>'}
    `;
  } catch (error) { setText("#owner-message", error.message); }
}

async function runOwnerUserAction(button) {
  const customerId = button.dataset.ownerUserAction;
  const action = button.dataset.action;
  if (!window.confirm(`${action} user ${customerId}?`)) return;
  button.disabled = true;
  try {
    await ownerApi(`/api/v1/owner/users/${encodeURIComponent(customerId)}/action`, {method: "POST", body: JSON.stringify({action})});
    setText("#owner-message", "User account was updated.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { button.disabled = false; }
}

function renderOwnerBotCreationReviews(payload, append = false) {
  const target = $("#owner-bot-creation-reviews");
  const rows = ownerPagedItems("botCreationReviews", payload, "reviews", append);
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((row) => {
    const payload = row.payload || {};
    return `
      <article class="owner-review-card">
        <div class="owner-order-head"><div><strong>${esc(payload.bot_title || payload.bot_username || "Bot request")}</strong><span>${esc(row.id)}</span></div><b>${esc(row.status)}</b></div>
        <div class="owner-order-meta"><span>Requester: ${esc(row.requester_id)}</span><span>Bot: ${esc(payload.bot_id || "-")}</span><span>Channel: ${esc(payload.channel || "-")}</span><span>${esc((row.review_reasons || []).join(", ") || "manual review")}</span></div>
        ${row.status === "pending" ? `<div class="owner-order-actions"><button class="primary compact" data-owner-bot-review="${esc(row.id)}" data-action="approve">Approve</button><button class="danger compact" data-owner-bot-review="${esc(row.id)}" data-action="reject">Reject</button></div>` : ""}
      </article>
    `;
  }).join("") : '<div class="notice">No bot creation reviews found.</div>';
  target.querySelectorAll("[data-owner-bot-review]").forEach((button) => button.addEventListener("click", () => runOwnerBotCreationReview(button)));
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("botCreationReviews", payload.pagination, "Load more reviews"));
  bindOwnerPagination(target);
}

async function runOwnerBotCreationReview(button) {
  const action = button.dataset.action;
  const warning = action === "approve"
    ? "Approve this reseller bot creation request and activate its paid trial?"
    : "Reject this reseller bot creation request?";
  if (!window.confirm(warning)) return;
  button.disabled = true;
  try {
    await ownerApi(`/api/v1/owner/bot-creation-reviews/${encodeURIComponent(button.dataset.ownerBotReview)}/action`, {method: "POST", body: JSON.stringify({action})});
    setText("#owner-message", "Bot creation review was updated.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { button.disabled = false; }
}

function renderOwnerRechargeReviews(payload, append = false) {
  const target = $("#owner-recharge-reviews");
  const rows = ownerPagedItems("recharge", payload, "reviews", append);
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((row) => `
    <article class="owner-review-card">
      <div class="owner-order-head"><div><strong>${esc(row.method || "طلب شحن")}</strong><span>${esc(row.id)}</span></div><b>${esc(row.status)}</b></div>
      <div class="owner-order-meta"><span>المستخدم: ${esc(row.user_id)}</span><span>المحفظة: ${esc(row.wallet_type)}</span><span>المبلغ: ${esc(row.amount)}</span><span>${row.has_proof ? "يوجد إثبات" : "بدون إثبات"}</span></div>
      ${row.proof_url ? `<div class="owner-order-actions"><a class="secondary compact button-link" href="${esc(row.proof_url)}" target="_blank" rel="noopener">عرض الإثبات</a><span>${esc(row.proof_filename || row.proof_content_type || "")}</span></div>` : ""}
      ${row.decision_note ? `<div class="notice">${esc(row.decision_note)}</div>` : ""}
      ${row.status === "pending" ? `<form class="owner-review-form" data-owner-recharge="${esc(row.id)}">
        <label><span>المبلغ المقبول</span><input name="approved_amount" type="number" min="0.0001" step="0.0001" value="${esc(row.amount)}"></label>
        <label><span>ملاحظة</span><input name="note" placeholder="ملاحظة القرار أو طلب إثبات جديد"></label>
        <div class="owner-order-actions"><button class="primary compact" name="action" value="accept">قبول</button><button class="danger compact" name="action" value="reject">رفض</button><button class="secondary compact" name="action" value="need_more_proof">طلب إثبات</button></div>
      </form>` : ""}
    </article>`).join("") : '<div class="notice">لا توجد طلبات شحن ضمن هذا الفلتر.</div>';
  target.querySelectorAll("[data-owner-recharge]").forEach((form) => form.addEventListener("submit", runOwnerRechargeAction));
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("recharge", payload.pagination, "Load more recharge reviews"));
  bindOwnerPagination(target);
}

async function runOwnerRechargeAction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const action = event.submitter?.value || "";
  const values = Object.fromEntries(new FormData(form).entries());
  if (action === "accept" && !window.confirm("سيتم إضافة الرصيد فعلياً إلى المحفظة. متابعة؟")) return;
  if (action === "reject" && !window.confirm("Reject this recharge request? This decision closes the request.")) return;
  setOwnerFormBusy(form, true);
  try {
    await ownerApi(`/api/v1/owner/recharge-reviews/${encodeURIComponent(form.dataset.ownerRecharge)}/action`, {method: "POST", body: JSON.stringify({...values, action})});
    setText("#owner-message", "تم تنفيذ إجراء طلب الشحن.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { setOwnerFormBusy(form, false); }
}

function renderOwnerIdentityReviews(payload, append = false) {
  const target = $("#owner-identity-reviews");
  const rows = ownerPagedItems("identity", payload, "reviews", append);
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
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("identity", payload.pagination, "Load more identity reviews"));
  bindOwnerPagination(target);
}

async function runOwnerIdentityAction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const action = event.submitter?.value || "";
  const values = Object.fromEntries(new FormData(form).entries());
  const warning = action === "approve"
    ? "Approve this identity verification request and unlock identity-gated access?"
    : "Reject this identity verification request?";
  if (!window.confirm(warning)) return;
  setOwnerFormBusy(form, true);
  try {
    await ownerApi(`/api/v1/owner/identity-reviews/${encodeURIComponent(form.dataset.ownerIdentity)}/action`, {method: "POST", body: JSON.stringify({...values, action})});
    setText("#owner-message", "تم تنفيذ قرار الهوية.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { setOwnerFormBusy(form, false); }
}

function renderOwnerSupportTickets(payload, append = false) {
  const target = $("#owner-support-tickets");
  const rows = ownerPagedItems("support", payload, "tickets", append);
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((row) => `
    <article class="owner-review-card">
      <div class="owner-order-head"><div><strong>تذكرة #${esc(row.ticket_no)} · ${esc(row.category)}</strong><span>${esc(row.full_name || row.username || row.user_id)}</span></div><b>${esc(row.status)}</b></div>
      <div class="owner-order-meta"><span>المستخدم: ${esc(row.user_id)}</span><span>المصدر: ${esc(row.scope)}</span><span>عدد الرسائل: ${esc(row.payload_count)}</span><span>فرز الخطأ: ${esc(row.bug_triage?.status || "-")}</span></div>
      ${row.status !== "solved" ? `<form class="owner-support-reply" data-owner-support-reply="${esc(row.id)}"><input name="message" required minlength="2" maxlength="3500" placeholder="اكتب الرد الذي سيصل للمستخدم عبر البوت"><button class="secondary compact" type="submit">إرسال الرد</button></form>` : ""}
      ${row.status !== "solved" ? `<form class="owner-support-reply" data-owner-support-attachment="${esc(row.id)}"><input name="attachment" type="file" required><input name="caption" maxlength="1024" placeholder="Attachment caption"><button class="secondary compact" type="submit">Send attachment</button></form>` : ""}
      <div class="owner-order-actions">
        <button class="secondary compact" data-owner-ticket-detail="${esc(row.id)}">Conversation</button>
        ${row.status !== "solved" ? `<button class="primary compact" data-owner-ticket="${esc(row.id)}" data-ticket-action="solve">حل التذكرة</button>` : ""}
        <button class="secondary compact" data-owner-ticket="${esc(row.id)}" data-ticket-action="bug_confirmed">تأكيد الخطأ</button>
        <button class="secondary compact" data-owner-ticket="${esc(row.id)}" data-ticket-action="not_bug">ليس خطأ</button>
        ${row.bug_triage?.status === "confirmed" && row.bug_reward?.status !== "paid" ? `<button class="primary compact" data-owner-ticket="${esc(row.id)}" data-ticket-action="bug_reward">Pay $1 reward</button>` : ""}
      </div>
    </article>`).join("") : '<div class="notice">لا توجد تذاكر دعم ضمن هذا الفلتر.</div>';
  target.querySelectorAll("[data-owner-ticket]").forEach((button) => button.addEventListener("click", () => runOwnerSupportAction(button)));
  target.querySelectorAll("[data-owner-ticket-detail]").forEach((button) => button.addEventListener("click", () => loadOwnerSupportDetail(button)));
  target.querySelectorAll("[data-owner-support-reply]").forEach((form) => form.addEventListener("submit", runOwnerSupportReply));
  target.querySelectorAll("[data-owner-support-attachment]").forEach((form) => form.addEventListener("submit", runOwnerSupportAttachment));
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("support", payload.pagination, "Load more support tickets"));
  bindOwnerPagination(target);
}

async function loadOwnerSupportDetail(button) {
  button.disabled = true;
  try {
    const payload = await ownerApi(`/api/v1/owner/support-tickets/${encodeURIComponent(button.dataset.ownerTicketDetail)}`);
    const card = button.closest(".owner-review-card");
    let conversation = card.querySelector(".owner-support-conversation");
    if (!conversation) {
      conversation = document.createElement("div");
      conversation.className = "owner-support-conversation";
      card.insertBefore(conversation, card.querySelector(".owner-support-reply"));
    }
    const messages = payload.messages || [];
    conversation.innerHTML = messages.length ? messages.map((message) => `
      <div class="owner-queue-row">
        <div><strong>${esc(message.direction === "owner_to_user" ? "Owner" : "Customer")}</strong><span>${esc(message.created_at)}</span></div>
        <p>${esc(message.text || message.caption || `[${message.kind || "Non-text Telegram payload"}${message.filename ? `: ${message.filename}` : ""}]`)}</p>
      </div>`).join("") : '<div class="notice">No stored text messages are available for this ticket. Older Telegram media may only exist in the support topic.</div>';
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

async function runOwnerSupportReply(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    await ownerApi(`/api/v1/owner/support-tickets/${encodeURIComponent(form.dataset.ownerSupportReply)}/action`, {method: "POST", body: JSON.stringify({action: "reply", message: form.elements.message.value})});
    setText("#owner-message", "تم إرسال الرد للمستخدم.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { button.disabled = false; }
}

async function runOwnerSupportAttachment(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const file = form.elements.attachment.files?.[0];
  if (!file) return setText("#owner-message", "Choose an attachment.");
  if (file.size > 8 * 1024 * 1024) return setText("#owner-message", "Attachment is larger than 8 MB.");
  const button = form.querySelector("button");
  const body = new FormData();
  body.append("attachment", file);
  body.append("caption", form.elements.caption.value || "");
  button.disabled = true;
  try {
    await ownerApi(`/api/v1/owner/support-tickets/${encodeURIComponent(form.dataset.ownerSupportAttachment)}/attachment`, {method: "POST", body, timeoutMs: 45000});
    setText("#owner-message", "Attachment was sent to the customer.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { button.disabled = false; }
}

async function runOwnerSupportAction(button) {
  const warnings = {
    solve: "Mark this support ticket as solved?",
    bug_confirmed: "Confirm this report as a valid bug?",
    not_bug: "Mark this report as not a bug?",
    bug_reward: "Pay the $1 bug reward to this user? This changes the wallet balance.",
  };
  const action = button.dataset.ticketAction;
  if (warnings[action] && !window.confirm(warnings[action])) return;
  button.disabled = true;
  try {
    await ownerApi(`/api/v1/owner/support-tickets/${encodeURIComponent(button.dataset.ownerTicket)}/action`, {method: "POST", body: JSON.stringify({action})});
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
    <div class="owner-routing-fields">
      <input name="chat_id" required inputmode="numeric" placeholder="Chat ID" value="${esc(target?.chat_id || "")}">
      <input name="message_thread_id" inputmode="numeric" placeholder="Topic ID" value="${esc(target?.message_thread_id || "")}">
    </div>
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
    <form class="owner-setting-card" data-owner-setting="numbers_markup_percent">
      <div><strong>هامش الأرقام</strong><span>نسبة تضاف إلى أسعار مزودي الأرقام</span></div>
      <input name="value" type="number" min="0" max="500" step="0.01" value="${esc(finance.numbers_markup_percent || 0)}" required>
      <button class="secondary compact" type="submit">حفظ</button>
    </form>`;

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

  renderOwnerBroadcastTools(routing);
  renderOwnerResellerDepositTools();
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
    await ownerApi("/api/v1/owner/settings", {
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
    await ownerApi(`/api/v1/owner/routing-targets/${encodeURIComponent(form.dataset.ownerRouting)}`, {
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
    await ownerApi("/api/v1/owner/settings", {
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
    await ownerApi(`/api/v1/owner/payment-methods/${encodeURIComponent(form.dataset.ownerPaymentMethod)}`, {
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

function ownerRefundDetailRows(review) {
  const order = review.order || {};
  const details = review.details || {};
  const serviceParts = [details.service || order.service, details.country || order.country].filter(Boolean).join(" / ");
  const rows = [
    ["Order ID", review.id],
    ["User / Reseller", [details.user_id, details.reseller_id].filter((item) => item !== undefined && item !== null && item !== "").join(" / ")],
    ["Provider order", details.provider_order_id],
    ["Number", details.number || order.number],
    ["Service / Country", serviceParts],
    ["Wait state", details.wait_state || order.wait_state],
    ["Created", details.created_at || order.created_at],
    ["Review opened", review.reviewed_at],
  ].filter(([, value]) => String(value || "").trim());
  return rows.map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
}

function renderOwnerRefundReviews(payload, append = false) {
  const target = $("#owner-refund-reviews");
  const rows = ownerPagedItems("refunds", payload, "reviews", append);
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((review) => {
    const details = review.details || {};
    return `
    <article class="owner-refund-review">
      <div class="owner-order-head">
        <div><strong>${esc(review.order?.service_name || review.order?.service || details.service || "طلب أرقام")}</strong><span>${esc(review.id || "")}</span></div>
        <b>${esc(review.status || "")}</b>
      </div>
      <div class="owner-order-meta">
        <span>السبب: ${esc(review.reason || "-")}</span>
        <span>حالة الطلب: ${esc(review.order?.public_status || review.order?.status || "-")}</span>
        <span>المزود: ${esc(review.order?.provider || details.provider || "-")}</span>
      </div>
      <div class="owner-review-details">${ownerRefundDetailRows(review)}</div>
      ${review.status === "resolved" ? `
        <div class="notice">القرار: ${esc(review.resolution || "-")}${review.notes ? ` · ${esc(review.notes)}` : ""}</div>` : `
        <form class="owner-refund-form" data-owner-refund="${esc(review.id)}">
          <label><span>القرار</span><input name="resolution" required minlength="3" placeholder="مثال: تم التحقق وإغلاق المراجعة"></label>
          <label><span>ملاحظات</span><input name="notes" placeholder="ملاحظات اختيارية"></label>
          <button class="primary compact" type="submit">إغلاق المراجعة</button>
        </form>`}
    </article>`;
  }).join("") : '<div class="notice">لا توجد مراجعات استرداد معلقة.</div>';
  target.querySelectorAll("[data-owner-refund]").forEach((form) => {
    form.addEventListener("submit", resolveOwnerRefundReview);
  });
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("refunds", payload.pagination, "Load more refund reviews"));
  bindOwnerPagination(target);
}

async function resolveOwnerRefundReview(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const orderId = form.dataset.ownerRefund;
  const resolution = String(form.elements.resolution?.value || "").trim();
  if (resolution.length < 3) {
    setText("#owner-message", "اكتب قرار واضح قبل إغلاق المراجعة.");
    form.elements.resolution?.focus();
    return;
  }
  if (!window.confirm("سيتم إغلاق علامة المراجعة فقط، ولن يتم تنفيذ استرداد مالي. متابعة؟")) return;
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const values = Object.fromEntries(new FormData(form).entries());
    values.resolution = resolution;
    await ownerApi(`/api/v1/owner/numbers/refund-reviews/${encodeURIComponent(orderId)}/resolve`, {
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

function renderOwnerCustomCatalog(payload) {
  const target = $("#owner-custom-catalog");
  const parent = payload.parent || {};
  const root = payload.root || {};
  const nodes = payload.nodes || [];
  target.classList.remove("empty");
  target.innerHTML = `
    <div class="owner-order-head">
      <div><strong>${esc(parent.name || "Catalog")}</strong><span>${esc(parent.id || "")}</span></div>
      <div class="owner-order-actions">
        ${parent.id && parent.id !== root.id ? `<button class="secondary compact" data-owner-catalog-folder="${esc(parent.parent_id || root.id)}">Back</button>` : ""}
        ${parent.id && parent.id !== root.id ? `<button class="secondary compact" data-owner-catalog-folder="${esc(root.id)}">Root</button>` : ""}
      </div>
    </div>
    <form class="owner-review-form" id="owner-catalog-create-form">
      <label><span>Type</span><select name="node_type"><option value="folder">Folder</option><option value="endpoint">Product</option></select></label>
      <label><span>Name</span><input name="name" required minlength="2" maxlength="100" placeholder="Folder or product name"></label>
      <label><span>Price USD</span><input name="price" type="number" min="0" step="0.01" value="0"></label>
      <label><span>Initial quantity</span><input name="available_qty" type="number" min="0" step="1" value="0"></label>
      <label><span>Minimum purchase</span><input name="min_qty" type="number" min="1" step="1" value="1"></label>
      <button class="primary compact" type="submit">Create</button>
    </form>
    <div id="owner-catalog-detail"></div>
    <div class="owner-action-list">
      ${nodes.length ? nodes.map((node) => `
        <div class="owner-action-row">
          <div><strong>${esc(node.name)}</strong><span>${esc(node.node_type)}${node.node_type === "endpoint" ? ` · ${esc(node.price)} USD · stock ${esc(node.available_qty)} · min ${esc(node.min_qty)}` : ""}</span></div>
          <div class="owner-order-actions">
            ${node.node_type === "folder" ? `<button class="secondary compact" data-owner-catalog-folder="${esc(node.id)}">Open</button>` : ""}
            <button class="secondary compact" data-owner-catalog-detail="${esc(node.id)}">Manage</button>
            <button class="secondary compact" data-owner-catalog-move="${esc(node.id)}" data-direction="up" title="Move up">↑</button>
            <button class="secondary compact" data-owner-catalog-move="${esc(node.id)}" data-direction="down" title="Move down">↓</button>
            <button class="danger compact" data-owner-catalog-delete="${esc(node.id)}">Disable</button>
          </div>
        </div>`).join("") : '<div class="notice">This folder is empty.</div>'}
    </div>`;
  $("#owner-catalog-create-form")?.addEventListener("submit", createOwnerCatalogNode);
  target.querySelectorAll("[data-owner-catalog-folder]").forEach((button) => button.addEventListener("click", () => openOwnerCatalogFolder(button.dataset.ownerCatalogFolder)));
  target.querySelectorAll("[data-owner-catalog-detail]").forEach((button) => button.addEventListener("click", () => loadOwnerCatalogNode(button.dataset.ownerCatalogDetail)));
  target.querySelectorAll("[data-owner-catalog-move]").forEach((button) => button.addEventListener("click", () => moveOwnerCatalogNode(button.dataset.ownerCatalogMove, button.dataset.direction)));
  target.querySelectorAll("[data-owner-catalog-delete]").forEach((button) => button.addEventListener("click", () => deleteOwnerCatalogNode(button.dataset.ownerCatalogDelete)));
}

async function openOwnerCatalogFolder(parentId) {
  ownerCatalogParentId = parentId || "";
  await loadOwnerDashboard();
}

async function createOwnerCatalogNode(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  values.parent_id = ownerCatalogParentId;
  values.catalog_type = $("#owner-catalog-type")?.value || "custom";
  values.price = Number(values.price || 0);
  values.available_qty = Number(values.available_qty || 0);
  values.min_qty = Number(values.min_qty || 1);
  try {
    await ownerApi("/api/v1/owner/custom-catalog/nodes", {method: "POST", body: JSON.stringify(values)});
    setText("#owner-message", "Catalog node was created.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

async function loadOwnerCatalogNode(nodeId) {
  try {
    const catalogType = $("#owner-catalog-type")?.value || "custom";
    const payload = await ownerApi(`/api/v1/owner/custom-catalog/nodes/${encodeURIComponent(nodeId)}?catalog_type=${encodeURIComponent(catalogType)}`);
    const node = payload.node || {};
    const target = $("#owner-catalog-detail");
    target.innerHTML = `
      <article class="owner-review-card">
        <div class="owner-order-head"><div><strong>Manage ${esc(node.name)}</strong><span>${esc(node.id)}</span></div><b>${esc(node.available_qty)} in stock</b></div>
        <form class="owner-review-form" data-owner-catalog-update="${esc(node.id)}">
          <label><span>Name</span><input name="name" value="${esc(node.name)}" required minlength="2" maxlength="100"></label>
          <label><span>Display text</span><textarea name="display_text" rows="3">${esc(node.display_text || "")}</textarea></label>
          ${node.node_type === "endpoint" ? `
            <label><span>Price USD</span><input name="price" type="number" min="0" step="0.01" value="${esc(node.price)}"></label>
            <label><span>Minimum purchase</span><input name="min_qty" type="number" min="1" step="1" value="${esc(node.min_qty)}"></label>
            <label><span>Low stock threshold</span><input name="low_stock_threshold" type="number" min="0" step="1" value="${esc(node.low_stock_threshold)}"></label>
            <label class="owner-toggle"><input name="preorder_enabled" type="checkbox" ${node.preorder_enabled ? "checked" : ""}> Enable preorder</label>
            <label><span>Product information</span><textarea name="product_info_text" rows="3">${esc(node.product_info_text || "")}</textarea></label>
            <label><span>Usage policy</span><textarea name="usage_policy_text" rows="3">${esc(node.usage_policy_text || "")}</textarea></label>
            <label><span>Automatic text delivery</span><textarea name="delivery_text" rows="3">${esc(node.delivery_type === "text" ? node.delivery_text || "" : "")}</textarea></label>` : ""}
          <button class="primary compact" type="submit">Save</button>
        </form>
        ${node.node_type === "endpoint" ? `<form class="owner-review-form" data-owner-catalog-inventory="${esc(node.id)}">
          <label><span>Stock mode</span><select name="mode"><option value="append">Append</option><option value="replace">Replace all</option></select></label>
          <label><span>Stock items, one per line</span><textarea name="payload" rows="6" placeholder="CODE-1&#10;CODE-2"></textarea></label>
          <button class="secondary compact" type="submit">Update stock</button>
          <button class="secondary compact" type="button" data-owner-catalog-stock-log="${esc(node.id)}">Stock log</button>
        </form>
        <div id="owner-catalog-stock-log"></div>
        <details><summary>Current stock (${esc(node.inventory_count)})</summary><pre>${esc((node.inventory_items || []).join("\n"))}</pre></details>` : ""}
      </article>`;
    target.querySelector("[data-owner-catalog-update]")?.addEventListener("submit", updateOwnerCatalogNode);
    target.querySelector("[data-owner-catalog-inventory]")?.addEventListener("submit", updateOwnerCatalogInventory);
    target.querySelector("[data-owner-catalog-stock-log]")?.addEventListener("click", () => loadOwnerCatalogStockLog(node.id));
  } catch (error) { setText("#owner-message", error.message); }
}

async function updateOwnerCatalogNode(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  values.catalog_type = $("#owner-catalog-type")?.value || "custom";
  if (form.elements.price) values.price = Number(values.price || 0);
  if (form.elements.min_qty) values.min_qty = Number(values.min_qty || 1);
  if (form.elements.low_stock_threshold) values.low_stock_threshold = Number(values.low_stock_threshold || 0);
  if (form.elements.preorder_enabled) values.preorder_enabled = form.elements.preorder_enabled.checked;
  if (!String(values.delivery_text || "").trim()) delete values.delivery_text;
  try {
    await ownerApi(`/api/v1/owner/custom-catalog/nodes/${encodeURIComponent(form.dataset.ownerCatalogUpdate)}`, {method: "PATCH", body: JSON.stringify(values)});
    setText("#owner-message", "Catalog product was updated.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

async function updateOwnerCatalogInventory(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  values.catalog_type = $("#owner-catalog-type")?.value || "custom";
  try {
    await ownerApi(`/api/v1/owner/custom-catalog/nodes/${encodeURIComponent(form.dataset.ownerCatalogInventory)}/inventory`, {method: "POST", body: JSON.stringify(values)});
    setText("#owner-message", "Product stock was updated.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

async function deleteOwnerCatalogNode(nodeId) {
  if (!window.confirm("Disable this catalog node and its children?")) return;
  try {
    const catalogType = $("#owner-catalog-type")?.value || "custom";
    await ownerApi(`/api/v1/owner/custom-catalog/nodes/${encodeURIComponent(nodeId)}?catalog_type=${encodeURIComponent(catalogType)}`, {method: "DELETE"});
    setText("#owner-message", "Catalog node was disabled.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

async function moveOwnerCatalogNode(nodeId, direction) {
  try {
    await ownerApi(`/api/v1/owner/custom-catalog/nodes/${encodeURIComponent(nodeId)}/action`, {
      method: "POST",
      body: JSON.stringify({action: "move", direction, catalog_type: $("#owner-catalog-type")?.value || "custom"}),
    });
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

async function loadOwnerCatalogStockLog(nodeId) {
  try {
    const catalogType = $("#owner-catalog-type")?.value || "custom";
    const payload = await ownerApi(`/api/v1/owner/custom-catalog/nodes/${encodeURIComponent(nodeId)}/stock-events?catalog_type=${encodeURIComponent(catalogType)}&limit=30`);
    const target = $("#owner-catalog-stock-log");
    target.innerHTML = (payload.events || []).length ? payload.events.map((event) => `
      <div class="owner-queue-row"><div><strong>${esc(event.event_type)}</strong><span>${esc(event.created_at)} · ${esc(event.note)}</span></div><b>${esc(event.qty_delta)}</b></div>`).join("") : '<div class="notice">No stock events recorded.</div>';
  } catch (error) { setText("#owner-message", error.message); }
}

function renderOwnerCustomPreorders(payload, append = false) {
  const target = $("#owner-custom-preorders");
  const rows = ownerPagedItems("preorders", payload, "preorders", append);
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((row) => {
    const actions = Array.isArray(row.available_actions) ? row.available_actions : [];
    return `
      <article class="owner-digital-order">
        <div class="owner-order-head">
          <div><strong>${esc(row.service_name || "Custom preorder")}</strong><span>${esc(row.id)}</span></div>
          <b>${esc(row.status)}</b>
        </div>
        <div class="owner-order-meta">
          <span>User: ${esc(row.buyer_user_id)}</span><span>Qty: ${esc(row.qty)}</span><span>Paid: ${esc(row.total_price)} USD</span><span>Queue: ${esc(row.queue_position || "-")}</span>
        </div>
        ${row.customer_note ? `<div class="notice">${esc(row.customer_note)}</div>` : ""}
        ${actions.length ? `
          <form class="owner-review-form" data-owner-preorder="${esc(row.id)}">
            ${actions.includes("fulfill") ? `<label><span>Delivery text</span><textarea name="delivery_text" rows="3" maxlength="3500" placeholder="The code, account details, or delivery instructions sent to the customer"></textarea></label>` : ""}
            ${actions.includes("reject") ? `<label><span>Rejection reason</span><input name="reason" maxlength="500" placeholder="Required when rejecting and refunding"></label>` : ""}
            <div class="owner-order-actions">
              ${actions.includes("fulfill") ? '<button class="primary compact" type="button" data-preorder-action="fulfill">Deliver and complete</button>' : ""}
              ${actions.includes("release") ? '<button class="secondary compact" type="button" data-preorder-action="release">Release claim</button>' : ""}
              ${actions.includes("reject") ? '<button class="danger compact" type="button" data-preorder-action="reject">Reject and refund</button>' : ""}
            </div>
            ${actions.includes("fulfill") ? `<div class="owner-support-reply"><input name="delivery_attachment" type="file"><input name="delivery_caption" maxlength="1024" placeholder="Attachment caption"><button class="secondary compact" type="button" data-preorder-attachment="send">Deliver attachment and complete</button></div>` : ""}
          </form>` : '<div class="notice">This preorder is closed.</div>'}
      </article>`;
  }).join("") : '<div class="notice">No custom preorders found for this filter.</div>';
  target.querySelectorAll("[data-preorder-action]").forEach((button) => button.addEventListener("click", () => runOwnerPreorderAction(button)));
  target.querySelectorAll("[data-preorder-attachment]").forEach((button) => button.addEventListener("click", () => runOwnerPreorderAttachment(button)));
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("preorders", payload.pagination, "Load more preorders"));
  bindOwnerPagination(target);
}

async function runOwnerPreorderAction(button) {
  const form = button.closest("[data-owner-preorder]");
  const action = button.dataset.preorderAction;
  const body = {action};
  if (action === "fulfill") {
    body.delivery_text = String(form.elements.delivery_text?.value || "").trim();
    if (body.delivery_text.length < 2) return setText("#owner-message", "Write the delivery text before completing the preorder.");
  }
  if (action === "reject") {
    body.reason = String(form.elements.reason?.value || "").trim();
    if (body.reason.length < 3) return setText("#owner-message", "Write the rejection reason before refunding.");
  }
  if (!window.confirm(action === "reject" ? "Reject this preorder and refund the customer?" : `Run ${action} on this preorder?`)) return;
  form.querySelectorAll("button").forEach((item) => { item.disabled = true; });
  try {
    await ownerApi(`/api/v1/owner/custom-preorders/${encodeURIComponent(form.dataset.ownerPreorder)}/action`, {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 45000,
    });
    setText("#owner-message", "Custom preorder was updated.");
    await loadOwnerDashboard();
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    form.querySelectorAll("button").forEach((item) => { item.disabled = false; });
  }
}

async function runOwnerPreorderAttachment(button) {
  const form = button.closest("[data-owner-preorder]");
  const file = form.elements.delivery_attachment.files?.[0];
  if (!file) return setText("#owner-message", "Choose a delivery attachment.");
  if (file.size > 8 * 1024 * 1024) return setText("#owner-message", "Attachment is larger than 8 MB.");
  if (!window.confirm("Deliver this attachment and complete the preorder?")) return;
  const body = new FormData();
  body.append("attachment", file);
  body.append("caption", form.elements.delivery_caption.value || "");
  form.querySelectorAll("button").forEach((item) => { item.disabled = true; });
  try {
    await ownerApi(`/api/v1/owner/custom-preorders/${encodeURIComponent(form.dataset.ownerPreorder)}/attachment`, {method: "POST", body, timeoutMs: 45000});
    setText("#owner-message", "Preorder attachment was delivered and the order was completed.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { form.querySelectorAll("button").forEach((item) => { item.disabled = false; }); }
}

const ownerDigitalActionLabels = {
  claim: "استلام",
  auto_api: "Auto API",
  future: "Future",
  complete: "إكمال",
  refund: "استرداد",
};

function ownerDigitalDetailRows(order) {
  const details = order.owner_details || {};
  const customerSummary = Object.values(order.customer_data || {}).filter(Boolean).slice(0, 3).join(" / ");
  const rows = [
    ["Order ID", order.id],
    ["User / Reseller", [details.user_id, details.reseller_id].filter(Boolean).join(" / ")],
    ["Source", details.source],
    ["Route", details.execution_route || details.fulfillment_mode],
    ["Fulfillment", details.fulfillment_status || order.manual_fulfillment_status],
    ["Provider ref", details.provider_ref_id],
    ["Provider order", details.provider_order_id || order.provider_order_id],
    ["Customer", order.player_id || customerSummary],
    ["Created", details.created_at || order.created_at],
    ["Updated", details.updated_at],
    ["Actor", details.route_updated_by || details.fulfilled_by || details.refunded_by],
    ["Note", details.action_note],
  ].filter(([, value]) => String(value || "").trim());
  return rows.map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
}

function ownerDigitalActionButtons(order, closed) {
  if (closed) {
    return '<div class="notice">هذا الطلب مغلق ولا يقبل إجراءات إضافية.</div>';
  }
  const actions = Array.isArray(order.available_actions) && order.available_actions.length
    ? order.available_actions
    : ["claim", "auto_api", "future", "complete", "refund"];
  return `<div class="owner-order-actions">${actions.map((action) => {
    const kind = action === "refund" ? "danger" : action === "complete" ? "primary" : "secondary";
    return `<button class="${kind} compact" type="button" data-owner-order="${esc(order.id)}" data-owner-action="${esc(action)}">${esc(ownerDigitalActionLabels[action] || action)}</button>`;
  }).join("")}</div>`;
}

function renderOwnerDigitalOrders(payload, append = false) {
  const target = $("#owner-digital-orders");
  const rows = ownerPagedItems("digital", payload, "orders", append);
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((order) => {
    const status = String(order.public_status || order.status || "").toLowerCase();
    const closed = ["completed", "success", "done", "refunded", "failed", "cancelled"].includes(status)
      || (Array.isArray(order.available_actions) && !order.available_actions.length);
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
        <span>العميل: ${esc(order.player_id || Object.values(order.customer_data || {}).filter(Boolean).slice(0, 2).join(" / ") || "-")}</span>
      </div>
      <div class="owner-digital-details">${ownerDigitalDetailRows(order)}</div>
      <details><summary>بيانات العميل</summary><pre>${esc(JSON.stringify(order.customer_data || {}, null, 2))}</pre></details>
      ${ownerDigitalActionButtons(order, closed)}
    </article>`;
  }).join("") : '<div class="notice">لا توجد طلبات رقمية ضمن هذا الفلتر.</div>';
  target.querySelectorAll("[data-owner-order]").forEach((button) => {
    button.addEventListener("click", () => runOwnerDigitalAction(button));
  });
  target.insertAdjacentHTML("beforeend", ownerPaginationButton("digital", payload.pagination, "Load more digital orders"));
  bindOwnerPagination(target);
}

async function runOwnerDigitalAction(button) {
  const orderId = button.dataset.ownerOrder;
  const action = button.dataset.ownerAction;
  const actionLabel = ownerDigitalActionLabels[action] || action;
  const warning = action === "refund"
    ? "سيتم إعادة المبلغ إلى محفظة العميل. هل تريد تنفيذ الاسترداد؟"
    : `هل تريد تنفيذ الإجراء ${actionLabel} على هذا الطلب؟`;
  if (!window.confirm(warning)) return;
  const card = button.closest(".owner-digital-order");
  card?.querySelectorAll("[data-owner-order]").forEach((item) => { item.disabled = true; });
  setText("#owner-message", `جاري تنفيذ ${actionLabel}...`);
  try {
    const result = await ownerApi(`/api/v1/owner/digital/orders/${encodeURIComponent(orderId)}/action`, {
      method: "POST",
      body: JSON.stringify({ action, notify_user: true }),
      timeoutMs: 45000,
    });
    setText("#owner-message", `تم تنفيذ ${ownerDigitalActionLabels[result.action] || result.action || actionLabel}.`);
    await loadOwnerDashboard();
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    card?.querySelectorAll("[data-owner-order]").forEach((item) => { item.disabled = false; });
  }
}
function orderIsOpen(row) {
  const status = String(orderStatus(row) || "").toLowerCase();
  return !["done", "completed", "complete", "delivered", "paid", "cancelled", "canceled", "refunded", "rejected", "failed"].includes(status);
}

function filteredCustomerOrders() {
  return customerOrderRows.filter((row) => {
    if (customerOrderFilter === "numbers") return row.channel_key === "numbers";
    if (customerOrderFilter === "digital") return row.channel_key === "digital";
    if (customerOrderFilter === "open") return orderIsOpen(row);
    if (customerOrderFilter === "done") return !orderIsOpen(row);
    return true;
  });
}

function renderOrders(rows = filteredCustomerOrders()) {
  const target = $("#orders-list");
  document.querySelectorAll("[data-order-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.orderFilter === customerOrderFilter);
  });
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

function openPanel(view, title = "", options = {}) {
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
  document.querySelectorAll(".app-view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === view);
  });
  if (title || customerViewTitles[view]) setPageTitle(title || customerViewTitles[view]);
  if (options.updateRoute !== false && view !== "owner") pushRoute(routeForView(view));
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
  pushRoute(`/app/${service}`);
  openPanel("workspace", config.title, { updateRoute: false });
  config.load();
}

document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const view = button.dataset.view;
    if (view === "owner") {
      activeOwnerTab = ownerTabForPath("/admin");
      openPanel("owner", "لوحة الإدارة", { updateRoute: false });
      applyOwnerTab(activeOwnerTab, true);
      loadOwnerDashboard();
      return;
    }
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

document.querySelectorAll("[data-owner-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    openPanel("owner", ownerTabTitles[button.dataset.ownerTab] || "لوحة الإدارة", { updateRoute: false });
    applyOwnerTab(button.dataset.ownerTab || "overview");
    loadOwnerDashboard();
  });
});

window.addEventListener("popstate", () => {
  if (!currentAccount) return;
  if (currentAccount.is_owner && window.location.pathname.startsWith("/admin")) {
    openPanel("owner", "لوحة الإدارة", { updateRoute: false });
    applyOwnerTab(ownerTabForPath(), false);
    return;
  }
  const pathView = viewForPath();
  if (pathView === "digital" || pathView === "numbers") {
    openService(pathView);
    return;
  }
  openPanel(pathView, "", { updateRoute: false });
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
$("#support-ticket-form")?.addEventListener("submit", submitSupportTicket);
document.querySelectorAll("[data-order-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    customerOrderFilter = button.dataset.orderFilter || "all";
    renderOrders();
  });
});
$("#refresh-owner")?.addEventListener("click", loadOwnerDashboard);
$("#owner-digital-filter")?.addEventListener("change", loadOwnerDashboard);
$("#owner-preorder-filter")?.addEventListener("change", loadOwnerDashboard);
$("#owner-catalog-type")?.addEventListener("change", () => { ownerCatalogParentId = ""; loadOwnerDashboard(); });
$("#owner-refunds-resolved")?.addEventListener("change", loadOwnerDashboard);
$("#owner-recharge-filter")?.addEventListener("change", loadOwnerDashboard);
$("#owner-identity-filter")?.addEventListener("change", loadOwnerDashboard);
$("#owner-support-filter")?.addEventListener("change", loadOwnerDashboard);
$("#owner-source-filter")?.addEventListener("change", loadOwnerDashboard);
$("#owner-audit-days")?.addEventListener("change", loadOwnerDashboard);
$("#owner-bot-review-filter")?.addEventListener("change", loadOwnerDashboard);

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

setMode(window.location.pathname === "/register" ? "register" : "login");

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
