const state = {
  apiKey: localStorage.getItem("phantomDigitalAdminKey") || "",
  status: "pending",
  loadingAction: "",
  orders: [],
};

const els = {
  apiKeyInput: document.getElementById("apiKeyInput"),
  saveKeyBtn: document.getElementById("saveKeyBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  status: document.getElementById("status"),
  tabs: Array.from(document.querySelectorAll(".tab")),
  diagnostics: document.getElementById("diagnostics"),
  orders: document.getElementById("orders"),
  template: document.getElementById("orderTemplate"),
};

els.apiKeyInput.value = state.apiKey;

function setStatus(text, tone = "") {
  els.status.textContent = text;
  els.status.className = `status ${tone}`.trim();
}

function headers() {
  return {
    Authorization: `Bearer ${state.apiKey}`,
    "Content-Type": "application/json",
  };
}

async function apiGet(path) {
  const response = await fetchWithTimeout(path, { headers: headers(), cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || payload.code || `Request failed: ${response.status}`);
  }
  return payload;
}

async function apiPost(path, body) {
  const response = await fetchWithTimeout(path, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body || {}),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || payload.code || `Request failed: ${response.status}`);
  }
  return payload;
}

async function fetchWithTimeout(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12000);
  try {
    return await fetch(path, { ...options, signal: controller.signal });
  } catch (err) {
    if (err && err.name === "AbortError") {
      throw new Error("Request timed out. Check API/database connectivity.");
    }
    throw err;
  } finally {
    window.clearTimeout(timeout);
  }
}

function money(value) {
  const n = Number(value || 0);
  return `$${n.toFixed(2)}`;
}

function shortId(value) {
  const text = String(value || "");
  if (text.length <= 14) return text || "-";
  return `${text.slice(0, 6)}…${text.slice(-6)}`;
}

function orderTitle(order) {
  return order.item_name || order.product_name || order.game_name || "Digital order";
}

function addField(dl, label, value) {
  const box = document.createElement("div");
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = label;
  dd.textContent = value || "-";
  box.append(dt, dd);
  dl.appendChild(box);
}

function actionButton(order, label, action, className = "") {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = label;
  btn.className = className;
  btn.disabled = state.loadingAction === `${order.id}:${action}`;
  btn.addEventListener("click", () => runAction(order.id, action));
  return btn;
}

function renderDiagnostics(diag) {
  if (!diag) {
    els.diagnostics.innerHTML = "";
    return;
  }
  const rows = [
    ["Products", diag.products_count],
    ["Sources", diag.sources_count],
    ["Issues", diag.issues_count],
    ["Status", diag.status],
  ];
  els.diagnostics.innerHTML = rows
    .map(([label, value]) => `<div class="diag-item"><span class="diag-label">${label}</span><span class="diag-value">${value ?? "-"}</span></div>`)
    .join("");
}

function renderOrders(orders) {
  els.orders.innerHTML = "";
  if (!orders.length) {
    const empty = document.createElement("div");
    empty.className = "order-card empty";
    empty.textContent = "No orders found for this filter.";
    els.orders.appendChild(empty);
    return;
  }
  for (const order of orders) {
    const node = els.template.content.firstElementChild.cloneNode(true);
    node.querySelector(".order-id").textContent = `#${shortId(order.id)}`;
    node.querySelector(".order-title").textContent = orderTitle(order);
    node.querySelector(".badge").textContent = order.public_status || order.status || "-";

    const grid = node.querySelector(".order-grid");
    addField(grid, "User data", order.player_id || Object.values(order.customer_data || {}).filter(Boolean).slice(0, 2).join(" / "));
    addField(grid, "Provider", order.provider);
    addField(grid, "Price", order.price_label || money(order.price));
    addField(grid, "Provider order", order.provider_order_id);
    addField(grid, "Kind", order.kind);
    addField(grid, "Created", order.created_at ? new Date(order.created_at).toLocaleString() : "");

    node.querySelector(".customer-data").textContent = JSON.stringify(order.customer_data || {}, null, 2);

    const actions = node.querySelector(".actions");
    actions.appendChild(actionButton(order, "Claim", "claim", "secondary"));
    actions.appendChild(actionButton(order, "Auto API", "auto_api"));
    actions.appendChild(actionButton(order, "Future", "future"));
    actions.appendChild(actionButton(order, "Complete", "complete"));
    actions.appendChild(actionButton(order, "Refund", "refund", "danger"));
    els.orders.appendChild(node);
  }
}

async function loadAll() {
  if (!state.apiKey) {
    setStatus("Enter an admin API key to load orders.");
    renderDiagnostics(null);
    renderOrders([]);
    return;
  }
  setStatus("Loading admin data...");
  try {
    const [diagResult, ordersResult] = await Promise.allSettled([
      apiGet("/api/v1/digital/source-diagnostics"),
      apiGet(`/api/v1/digital/admin/orders?status=${encodeURIComponent(state.status)}&limit=50`),
    ]);
    if (diagResult.status === "fulfilled") {
      renderDiagnostics(diagResult.value.diagnostics);
    } else {
      renderDiagnostics(null);
    }
    if (ordersResult.status === "rejected") {
      throw ordersResult.reason;
    }
    state.orders = ordersResult.value.orders || [];
    renderOrders(state.orders);
    setStatus(`Loaded ${state.orders.length} orders.`, "success");
  } catch (err) {
    setStatus(err.message || "Failed to load admin data.", "error");
  }
}

async function runAction(orderId, action) {
  if (!state.apiKey || !orderId) return;
  const confirmText = action === "refund" ? "Refund this order to the customer wallet?" : `Run ${action} for this order?`;
  if (!window.confirm(confirmText)) return;
  state.loadingAction = `${orderId}:${action}`;
  renderOrders(state.orders);
  setStatus(`Running ${action}...`);
  try {
    await apiPost(`/api/v1/digital/orders/${encodeURIComponent(orderId)}/manual-action`, { action });
    setStatus(`${action} completed.`, "success");
    await loadAll();
  } catch (err) {
    setStatus(err.message || `${action} failed.`, "error");
  } finally {
    state.loadingAction = "";
  }
}

els.saveKeyBtn.addEventListener("click", () => {
  state.apiKey = els.apiKeyInput.value.trim();
  localStorage.setItem("phantomDigitalAdminKey", state.apiKey);
  loadAll();
});

els.refreshBtn.addEventListener("click", loadAll);

for (const tab of els.tabs) {
  tab.addEventListener("click", () => {
    state.status = tab.dataset.status || "pending";
    els.tabs.forEach((item) => item.classList.toggle("is-active", item === tab));
    loadAll();
  });
}

loadAll();
