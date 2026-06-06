const authView = document.querySelector("#auth-view");
const accountView = document.querySelector("#account-view");
const form = document.querySelector("#auth-form");
const emailInput = document.querySelector("#email");
const passwordInput = document.querySelector("#password");
const formError = document.querySelector("#form-error");
const submitButton = document.querySelector("#submit-button");
const telegramAction = document.querySelector("#telegram-action");
const accountMessage = document.querySelector("#account-message");
const sendEmailCodeButton = document.querySelector("#send-email-code");
const verifyEmailCodeButton = document.querySelector("#verify-email-code");
let mode = "login";
let currentAccount = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
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
  const response = await fetch(path, { credentials: "same-origin", ...options, method, headers });
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = {}; }
  if (!response.ok) throw new Error(data.message || text || "تعذر إكمال الطلب");
  return data;
}

function showAccount(account) {
  currentAccount = account;
  authView.hidden = true;
  accountView.hidden = false;
  document.querySelector(".form-wrap").classList.add("dashboard-mode");
  document.querySelector("#account-email").textContent = account.email;
  document.querySelector("#settings-email").textContent = account.email;
  document.querySelector("#customer-id").textContent = account.customer_id;
  document.querySelector("#telegram-status").textContent = account.telegram_linked ? "مربوط" : "غير مربوط";
  telegramAction.textContent = account.telegram_linked ? "فك الربط" : "ربط Telegram";
  applyEmailState(account);
  applyIdentityState(account.identity_status);
  loadDashboard();
}

function applyEmailState(account) {
  const verified = Boolean(account.email_verified);
  const canBuy = Boolean(account.capabilities?.buy_services);
  document.querySelector("#email-status").textContent = verified ? "مؤكد" : "غير مؤكد";
  document.querySelector("#email-verification-row").hidden = verified;
  document.querySelector("#email-code-row").hidden = true;
  document.querySelector("#purchase-readiness").hidden = canBuy;
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
  document.querySelector("#identity-status").textContent = label;
  document.querySelector("#identity-summary").textContent = label;
  const form = document.querySelector("#identity-form");
  form.hidden = ["pending", "approved"].includes(status);
  const cardexLink = document.querySelector("#cardex-link");
  const allowed = status === "approved";
  cardexLink.classList.toggle("locked", !allowed);
  cardexLink.href = allowed ? "/mini/cardex" : "#";
  cardexLink.querySelector("b").textContent = allowed ? "فتح" : "مقفل";
  document.querySelector("#cardex-reason").textContent = allowed ? "بيع البطاقات والسحب" : "يتطلب تأكيد الهوية";
}

function renderRows(target, rows, formatter) {
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map(formatter).join("") : "لا توجد بيانات حتى الآن.";
}

async function loadDashboard() {
  const activity = document.querySelector("#activity-list");
  try {
    const [digitalAccount, digitalOrders, numberOrders] = await Promise.all([
      api("/api/v1/digital/account"),
      api("/api/v1/digital/orders?limit=20"),
      api("/api/v1/numbers/orders?limit=20"),
    ]);
    document.querySelector("#wallet-balance").textContent = digitalAccount.wallet?.balance_label || "$0.00";
    const digitalRows = digitalOrders.orders || digitalOrders.items || [];
    const numberRows = numberOrders.orders || numberOrders.items || [];
    document.querySelector("#digital-order-count").textContent = digitalRows.length;
    document.querySelector("#numbers-order-count").textContent = numberRows.length;
    renderRows(activity, digitalAccount.recent_activity || [], (row) => `
      <div class="data-row"><div><strong>${esc(row.reason || "حركة رصيد")}</strong><span>${esc(row.created_at || "")}</span></div><b>${row.direction === "debit" ? "-" : "+"}${esc(row.amount_label || "")}</b></div>`);
    renderOrders([...digitalRows.map((row) => ({ ...row, channel: "رقمي" })), ...numberRows.map((row) => ({ ...row, channel: "أرقام" }))]);
  } catch (error) {
    activity.textContent = "تعذر تحميل بيانات الحساب حالياً.";
  }
}

function renderOrders(rows) {
  const target = document.querySelector("#orders-list");
  renderRows(target, rows, (row) => `
    <div class="data-row"><div><strong>${esc(row.title || row.service_name || row.service_id || "طلب")}</strong><span>${esc(row.channel)} · ${esc(row.created_at || "")}</span></div><b>${esc(row.status || "")}</b></div>`);
}

document.querySelectorAll(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => {
  const view = button.dataset.view;
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => item.classList.toggle("active", item === button));
  document.querySelectorAll(".app-view").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === view));
  document.querySelector("#view-title").textContent = button.textContent;
}));

document.querySelector("#cardex-link").addEventListener("click", (event) => {
  if (event.currentTarget.classList.contains("locked")) event.preventDefault();
});

document.querySelector("#refresh-orders").addEventListener("click", loadDashboard);

sendEmailCodeButton.addEventListener("click", async () => {
  accountMessage.textContent = "";
  sendEmailCodeButton.disabled = true;
  try {
    const data = await api("/api/v1/auth/email/send-code", { method: "POST" });
    if (data.status === "already_verified") {
      const fresh = await api("/api/v1/auth/me");
      showAccount(fresh.account);
      accountMessage.textContent = "البريد مؤكد مسبقاً.";
      return;
    }
    document.querySelector("#email-code-row").hidden = false;
    const debug = data.debug_code ? ` كود الاختبار: ${data.debug_code}` : "";
    accountMessage.textContent = data.status === "sent" ? "تم إرسال كود التأكيد إلى بريدك." : `تم إنشاء الكود.${debug}`;
  } catch (error) {
    accountMessage.textContent = error.message;
  } finally {
    sendEmailCodeButton.disabled = false;
  }
});

verifyEmailCodeButton.addEventListener("click", async () => {
  accountMessage.textContent = "";
  verifyEmailCodeButton.disabled = true;
  try {
    const code = document.querySelector("#email-code").value.trim();
    const data = await api("/api/v1/auth/email/verify", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
    showAccount(data.account);
    accountMessage.textContent = "تم تأكيد البريد وتفعيل الشراء.";
  } catch (error) {
    accountMessage.textContent = error.message === "invalid or expired code" ? "الكود غير صحيح أو منتهي." : error.message;
  } finally {
    verifyEmailCodeButton.disabled = false;
  }
});

document.querySelector("#identity-form").addEventListener("submit", async (event) => {
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
  document.querySelector("#form-title").textContent = mode === "login" ? "أهلاً بعودتك" : "إنشاء حساب جديد";
  document.querySelector("#form-subtitle").textContent = mode === "login"
    ? "أدخل بريدك وكلمة المرور للمتابعة."
    : "استخدم بريداً تستطيع الوصول إليه وكلمة مرور قوية.";
  submitButton.textContent = mode === "login" ? "تسجيل الدخول" : "إنشاء الحساب";
  passwordInput.autocomplete = mode === "login" ? "current-password" : "new-password";
}

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => setMode(tab.dataset.mode)));
document.querySelector("#toggle-password").addEventListener("click", (event) => {
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
    if (!data.telegram_url) throw new Error("رابط Telegram غير متوفر حالياً.");
    window.location.href = data.telegram_url;
  } catch (error) {
    accountMessage.textContent = error.message;
  }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  await api("/api/v1/auth/logout", { method: "POST" });
  window.location.reload();
});

api("/api/v1/auth/me").then((data) => showAccount(data.account)).catch(() => {});
