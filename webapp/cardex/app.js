const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const state = {
  rules: [],
  isAdmin: false,
  hasAuth: false,
  view: "brands",
  brand: "",
  regionKey: "",
  search: "",
};

const BRAND_META = {
  AMAZON: { mark: "a", tone: "tone-amazon" },
  ITUNES: { mark: "IT", tone: "tone-itunes" },
  APPLE: { mark: "A", tone: "tone-itunes" },
  RAZER: { mark: "Z", tone: "tone-razer" },
  "RAZER GOLD": { mark: "Z", tone: "tone-razer" },
  STEAM: { mark: "S", tone: "tone-steam" },
  WALMART: { mark: "W", tone: "tone-walmart" },
  TARGET: { mark: "TG", tone: "tone-target" },
  MASTERCARD: { mark: "MC", tone: "tone-mastercard" },
  VISA: { mark: "V", tone: "tone-visa" },
  PAYPAL: { mark: "P", tone: "tone-paypal" },
  PAYEER: { mark: "P", tone: "tone-payeer" },
  USDT: { mark: "T", tone: "tone-usdt" },
  UBER: { mark: "U", tone: "tone-uber" },
  STARBUCKS: { mark: "SB", tone: "tone-starbucks" },
  PLAYSTATION: { mark: "PS", tone: "tone-playstation" },
};

const content = document.getElementById("content");
const statusEl = document.getElementById("status");
const searchInput = document.getElementById("searchInput");
const refreshBtn = document.getElementById("refreshBtn");
const pricesTab = document.getElementById("pricesTab");
const cardsTab = document.getElementById("cardsTab");
const walletTab = document.getElementById("walletTab");
const withdrawTab = document.getElementById("withdrawTab");
const adminTab = document.getElementById("adminTab");
const modal = document.getElementById("modal");
const priceForm = document.getElementById("priceForm");
const closeModal = document.getElementById("closeModal");
const sellModal = document.getElementById("sellModal");
const sellForm = document.getElementById("sellForm");
const closeSellModal = document.getElementById("closeSellModal");
const sellSummary = document.getElementById("sellSummary");
const quoteBox = document.getElementById("quoteBox");
const withdrawModal = document.getElementById("withdrawModal");
const withdrawForm = document.getElementById("withdrawForm");
const closeWithdrawModal = document.getElementById("closeWithdrawModal");
const adminFormModal = document.getElementById("adminFormModal");
const adminForm = document.getElementById("adminForm");
const adminFormTitle = document.getElementById("adminFormTitle");
const adminFormSubtitle = document.getElementById("adminFormSubtitle");
const adminFormFields = document.getElementById("adminFormFields");
const adminFormSubmit = document.getElementById("adminFormSubmit");
const closeAdminFormModal = document.getElementById("closeAdminFormModal");
let adminFormHandler = null;

function initData() {
  return tg?.initData || new URLSearchParams(location.search).get("tgWebAppData") || "";
}

function hasInitData() {
  return Boolean(initData());
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), "X-Telegram-Init-Data": initData() };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...options, headers, cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function norm(text) {
  return String(text || "").trim().toLowerCase();
}

function clear() {
  content.replaceChildren();
  statusEl.textContent = "";
  statusEl.classList.remove("error");
}

function setActiveTab(tab) {
  for (const item of [pricesTab, cardsTab, walletTab, withdrawTab, adminTab]) item.classList.remove("active");
  tab.classList.add("active");
  searchInput.value = "";
  state.search = "";
}

function updateAuthTabs() {
  state.hasAuth = hasInitData();
  for (const tab of [cardsTab, walletTab, withdrawTab]) {
    tab.classList.toggle("hidden", !state.hasAuth);
  }
}

function renderAuthRequired(title) {
  setActiveTab(pricesTab);
  state.view = "brands";
  clear();
  content.append(heading(title, "This section needs Telegram login"));
  setNotice("Open CardEX from the bot mini app button to access your cards, wallet, and withdrawals.");
  renderBrands();
}

function setError(text) {
  statusEl.textContent = text;
  statusEl.classList.add("error");
}

function setNotice(text) {
  statusEl.textContent = text;
  statusEl.classList.remove("error");
}

async function withSubmitLock(form, label, fn) {
  if (form.dataset.busy === "1") return;
  const submit = form.querySelector('button[type="submit"]');
  const oldText = submit?.textContent || "";
  form.dataset.busy = "1";
  if (submit) {
    submit.disabled = true;
    submit.textContent = label;
  }
  try {
    await fn();
  } finally {
    form.dataset.busy = "0";
    if (submit) {
      submit.disabled = false;
      submit.textContent = oldText;
    }
  }
}

function button(cls, text, fn) {
  const el = document.createElement("button");
  el.type = "button";
  el.className = cls;
  el.textContent = text;
  el.addEventListener("click", fn);
  return el;
}

function fieldLabel(field) {
  const label = document.createElement("label");
  label.textContent = field.label;
  let input;
  if (field.type === "textarea") {
    input = document.createElement("textarea");
    input.rows = field.rows || 4;
  } else {
    input = document.createElement("input");
    input.type = field.type || "text";
  }
  input.name = field.name;
  input.value = field.value || "";
  input.placeholder = field.placeholder || "";
  input.required = Boolean(field.required);
  if (field.inputmode) input.inputMode = field.inputmode;
  label.append(input);
  return label;
}

function openAdminForm({ title, subtitle = "", submitText = "Save", fields = [], onSubmit }) {
  adminForm.reset();
  adminFormTitle.textContent = title;
  adminFormSubtitle.textContent = subtitle;
  adminFormSubtitle.classList.toggle("hidden", !subtitle);
  adminFormSubmit.textContent = submitText;
  adminFormFields.replaceChildren(...fields.map(fieldLabel));
  adminFormHandler = onSubmit;
  adminFormModal.classList.remove("hidden");
}

function closeAdminForm() {
  adminFormModal.classList.add("hidden");
  adminFormHandler = null;
}

function openAdminInfo({ title, subtitle = "", text = "" }) {
  adminForm.reset();
  adminFormTitle.textContent = title;
  adminFormSubtitle.textContent = subtitle;
  adminFormSubtitle.classList.toggle("hidden", !subtitle);
  adminFormSubmit.textContent = "Close";
  const pre = document.createElement("pre");
  pre.className = "info-box";
  pre.textContent = text;
  adminFormFields.replaceChildren(pre);
  adminFormHandler = async () => {};
  adminFormModal.classList.remove("hidden");
}

function heading(title, subtitle = "") {
  const box = document.createElement("div");
  box.className = "section-title";
  const wrap = document.createElement("div");
  const h = document.createElement("h2");
  h.textContent = title;
  wrap.append(h);
  if (subtitle) {
    const p = document.createElement("p");
    p.textContent = subtitle;
    wrap.append(p);
  }
  box.append(wrap);
  if (state.isAdmin && ["brands", "regions", "rules"].includes(state.view)) box.append(button("primary", "Add", openModal));
  return box;
}

function brandRows() {
  const map = new Map();
  for (const row of state.rules) {
    const brand = String(row.brand || "-").toUpperCase();
    if (!map.has(brand)) map.set(brand, { brand, count: 0, regions: new Set() });
    map.get(brand).count += 1;
    map.get(brand).regions.add(`${row.region || "GLOBAL"}|${row.currency || "USD"}`);
  }
  return Array.from(map.values()).sort((a, b) => a.brand.localeCompare(b.brand));
}

function regionRows(brand) {
  const map = new Map();
  for (const row of state.rules.filter((item) => item.brand === brand)) {
    const key = `${row.region || "GLOBAL"}|${row.currency || "USD"}`;
    if (!map.has(key)) map.set(key, { key, region: row.region || "GLOBAL", currency: row.currency || "USD", count: 0 });
    map.get(key).count += 1;
  }
  return Array.from(map.values()).sort((a, b) => a.region.localeCompare(b.region) || a.currency.localeCompare(b.currency));
}

function filtered(items, fields) {
  const q = norm(state.search);
  if (!q) return items;
  return items.filter((item) => fields.some((field) => norm(item[field]).includes(q)));
}

function brandMeta(brand) {
  const key = String(brand || "").toUpperCase();
  return BRAND_META[key] || { mark: key.slice(0, 2) || "CX", tone: "tone-generic" };
}

function regionPreview(row) {
  return Array.from(row.regions).slice(0, 3).map((item) => item.split("|")[0]).join(" / ");
}

function renderBrands() {
  state.view = "brands";
  state.brand = "";
  state.regionKey = "";
  clear();
  content.append(heading("Card Brands", "Choose a card type, then country, then price category"));
  const grid = document.createElement("div");
  grid.className = "brand-grid";
  for (const row of filtered(brandRows(), ["brand"])) {
    const meta = brandMeta(row.brand);
    const tile = button(`brand-card ${meta.tone}`, "", () => renderRegions(row.brand));
    tile.innerHTML = `
      <div class="brand-poster">
        <span class="brand-orb">${meta.mark}</span>
        <strong>${row.brand}</strong>
        <span>${regionPreview(row) || "GLOBAL"}</span>
      </div>
      <div class="brand-caption">${row.regions.size} regions - ${row.count} categories</div>
    `;
    grid.append(tile);
  }
  if (!grid.children.length) statusEl.textContent = "No brands found.";
  content.append(grid);
}

function renderRegions(brand) {
  state.view = "regions";
  state.brand = brand;
  state.regionKey = "";
  clear();
  content.append(button("ghost", "Back", renderBrands));
  content.append(heading(brand, "Choose country or region"));
  const grid = document.createElement("div");
  grid.className = "region-grid";
  for (const row of filtered(regionRows(brand), ["region", "currency"])) {
    const tile = button("region-card", "", () => renderRules(brand, row.key));
    tile.innerHTML = `<strong>${row.region}</strong><span>${row.currency}</span><small>${row.count} categories</small>`;
    grid.append(tile);
  }
  if (!grid.children.length) statusEl.textContent = "No regions found.";
  content.append(grid);
}

function renderRules(brand, regionKey) {
  state.view = "rules";
  state.brand = brand;
  state.regionKey = regionKey;
  const [region, currency] = String(regionKey).split("|");
  clear();
  content.append(button("ghost", "Back", () => renderRegions(brand)));
  content.append(heading(`${brand} - ${region}`, `${currency} price categories`));
  const list = document.createElement("div");
  list.className = "list";
  const rows = state.rules
    .filter((row) => row.brand === brand && `${row.region}|${row.currency}` === regionKey)
    .filter((row) => !state.search || norm(`${row.label} ${row.note} ${row.customer_rate}`).includes(norm(state.search)));
  for (const row of rows) {
    const item = document.createElement("article");
    item.className = "rule";
    item.innerHTML = `
      <div class="rule-top"><span class="value">${row.label}</span><span class="rate">${row.customer_rate}%</span></div>
      <div class="muted">${row.currency} - trader ${row.trader_rate || row.customer_rate}%</div>
      ${row.note ? `<div class="note">${row.note}</div>` : ""}
    `;
    if (state.isAdmin) {
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.append(button("primary", "Sell", () => openSellModal(row)));
      actions.append(button("ghost danger", "Delete", () => deleteRule(row.id)));
      item.append(actions);
    } else {
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.append(button("primary", "Sell", () => openSellModal(row)));
      item.append(actions);
    }
    list.append(item);
  }
  if (!list.children.length) statusEl.textContent = "No categories found.";
  content.append(list);
}

async function loadPrices() {
  updateAuthTabs();
  setActiveTab(pricesTab);
  statusEl.textContent = "Loading prices...";
  try {
    const data = await api("/mini/cardex/api/prices");
    state.rules = Array.isArray(data.rules) ? data.rules : [];
    state.isAdmin = Boolean(data.is_admin);
    adminTab.classList.toggle("hidden", !state.isAdmin);
    renderBrands();
  } catch (err) {
    clear();
    setError("Could not load CardEX prices.");
  }
}

function money(value) {
  const amount = Number(value || 0);
  return `$${amount.toFixed(2)}`;
}

function statusLabel(value) {
  return String(value || "-").replaceAll("_", " ");
}

async function renderMyCards() {
  if (!hasInitData()) return renderAuthRequired("My Cards");
  setActiveTab(cardsTab);
  state.view = "mycards";
  clear();
  content.append(heading("My Cards", "Submitted cards and review status"));
  statusEl.textContent = "Loading cards...";
  try {
    const data = await api("/mini/cardex/api/cards");
    clear();
    content.append(heading("My Cards", "Submitted cards and review status"));
    const list = document.createElement("div");
    list.className = "list";
    for (const row of data.cards || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand} ${row.denomination} ${row.currency}</span><span class="rate">${money(row.customer_value_usd)}</span></div>
        <div class="muted">${row.region} - ${statusLabel(row.status)} - ${row.customer_rate}%</div>
        ${row.review_notes ? `<div class="note">${row.review_notes}</div>` : ""}
      `;
      list.append(item);
    }
    if (!list.children.length) statusEl.textContent = "No cards submitted yet.";
    content.append(list);
  } catch (err) {
    clear();
    setError("Could not load your cards. Open CardEX from the bot mini app button.");
  }
}

async function renderWallet() {
  if (!hasInitData()) return renderAuthRequired("Wallet");
  setActiveTab(walletTab);
  state.view = "wallet";
  clear();
  content.append(heading("Wallet", "CardEX balance summary"));
  statusEl.textContent = "Loading wallet...";
  try {
    const data = await api("/mini/cardex/api/wallet");
    clear();
    content.append(heading("Wallet", "CardEX balance summary"));
    const wallet = data.wallet || {};
    const grid = document.createElement("div");
    grid.className = "wallet-grid";
    for (const row of [
      ["Available", wallet.available_usd],
      ["Pending", wallet.pending_usd],
      ["Locked", wallet.locked_usd],
    ]) {
      const tile = document.createElement("article");
      tile.className = "wallet-card";
      tile.innerHTML = `<span>${row[0]}</span><strong>${money(row[1])}</strong>`;
      grid.append(tile);
    }
    content.append(grid);
    const actions = document.createElement("div");
    actions.className = "wallet-actions";
    actions.append(button("primary", "Request withdrawal", openWithdrawModal));
    actions.append(button("ghost", "Withdrawal history", renderWithdrawals));
    content.append(actions);
  } catch (err) {
    clear();
    setError("Could not load wallet. Open CardEX from the bot mini app button.");
  }
}

async function renderWithdrawals() {
  if (!hasInitData()) return renderAuthRequired("Withdrawals");
  setActiveTab(withdrawTab);
  state.view = "withdrawals";
  clear();
  const title = heading("Withdrawals", "Request payout and follow status");
  title.append(button("primary", "Request", openWithdrawModal));
  content.append(title);
  statusEl.textContent = "Loading withdrawals...";
  try {
    const data = await api("/mini/cardex/api/withdrawals");
    clear();
    const refreshedTitle = heading("Withdrawals", "Request payout and follow status");
    refreshedTitle.append(button("primary", "Request", openWithdrawModal));
    content.append(refreshedTitle);
    const list = document.createElement("div");
    list.className = "list";
    for (const row of data.withdrawals || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${money(row.amount_usd)}</span><span class="rate">${statusLabel(row.status)}</span></div>
        <div class="muted">${row.payout_currency} payout - ${row.id}</div>
        ${row.notes ? `<div class="note">${row.notes}</div>` : ""}
      `;
      list.append(item);
    }
    if (!list.children.length) statusEl.textContent = "No withdrawal requests yet.";
    content.append(list);
  } catch (err) {
    clear();
    setError("Could not load withdrawals. Open CardEX from the bot mini app button.");
  }
}

function adminCardActions(row) {
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(button("primary", "Accept", () => updateAdminCard(row.id, "accept")));
  actions.append(button("ghost danger", "Reject", () => updateAdminCard(row.id, "reject")));
  return actions;
}

function adminWithdrawalActions(row) {
  const actions = document.createElement("div");
  actions.className = "actions";
  if (row.status !== "approved") actions.append(button("primary", "Approve", () => updateAdminWithdrawal(row.id, "approve")));
  actions.append(button("ghost", "Paid", () => updateAdminWithdrawal(row.id, "paid")));
  actions.append(button("ghost danger", "Reject", () => updateAdminWithdrawal(row.id, "reject")));
  return actions;
}

function adminMissingPricingActions(row) {
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(button("primary", "Set price", () => setMissingPricing(row)));
  return actions;
}

function adminTraderActions(row) {
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(button("primary", "Statement", () => showTraderStatement(row)));
  actions.append(button("ghost", "Batch cards", () => createTraderBatch(row)));
  actions.append(button("ghost", "Payment", () => recordTraderPayment(row)));
  return actions;
}

function miniList(items) {
  return Object.entries(items || {}).map(([key, value]) => `${key}: ${value}`).join(" - ") || "none";
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

async function renderAdmin() {
  if (!state.isAdmin) return loadPrices();
  setActiveTab(adminTab);
  state.view = "admin";
  clear();
  content.append(heading("Admin Queue", "Review submitted cards and open withdrawals"));
  statusEl.textContent = "Loading admin queue...";
  try {
    const data = await api("/mini/cardex/api/admin/queue");
    clear();
    content.append(heading("Admin Queue", "Review submitted cards and open withdrawals"));

    const report = data.today_report || {};
    const reportTitle = document.createElement("div");
    reportTitle.className = "section-title";
    reportTitle.innerHTML = "<h2>Today Report</h2>";
    content.append(reportTitle);
    const reportBox = document.createElement("article");
    reportBox.className = "rule";
    reportBox.innerHTML = `
      <div class="rule-top"><span class="value">${report.date || ""}</span><span class="rate">${report.cards_total || 0} cards</span></div>
      <div class="muted">Pending ${report.pending_reviews || 0} - Missing ${report.missing_pricing || 0} - Withdrawals ${report.open_withdrawals || 0}</div>
      <div class="note">Customer value ${money(report.customer_value_usd)} - Trader value ${money(report.trader_value_usd)}</div>
      <div class="note">Status: ${miniList(report.by_status)}</div>
      <div class="note">Brands: ${miniList(report.by_brand)}</div>
    `;
    content.append(reportBox);

    const exportTitle = document.createElement("div");
    exportTitle.className = "section-title";
    exportTitle.innerHTML = "<h2>Today Exports</h2>";
    content.append(exportTitle);
    const exportsList = document.createElement("div");
    exportsList.className = "list";
    for (const row of data.today_exports || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand}</span><span class="rate">${row.count} cards</span></div>
        <div class="muted">${row.filename}</div>
      `;
      item.append(button("primary", "Copy", async () => {
        try {
          await copyText(row.content || "");
          statusEl.textContent = "Export copied.";
        } catch (err) {
          openAdminInfo({ title: row.filename, text: row.content || "No export content." });
        }
      }));
      exportsList.append(item);
    }
    if (!exportsList.children.length) exportsList.append(emptyLine("No cards to export today."));
    content.append(exportsList);

    const cardTitle = document.createElement("div");
    cardTitle.className = "section-title";
    cardTitle.innerHTML = "<h2>Cards</h2>";
    content.append(cardTitle);
    const cards = document.createElement("div");
    cards.className = "list";
    for (const row of data.cards || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand} ${row.denomination} ${row.currency}</span><span class="rate">${money(row.customer_value_usd)}</span></div>
        <div class="muted">${row.region} - ${statusLabel(row.status)} - seller ${row.seller_user_id}</div>
        <div class="note">Code: ${row.code}${row.pin ? ` | PIN: ${row.pin}` : ""}</div>
      `;
      item.append(adminCardActions(row));
      cards.append(item);
    }
    if (!cards.children.length) cards.append(emptyLine("No cards waiting for review."));
    content.append(cards);

    const withdrawalTitle = document.createElement("div");
    withdrawalTitle.className = "section-title";
    withdrawalTitle.innerHTML = "<h2>Withdrawals</h2>";
    content.append(withdrawalTitle);
    const withdrawals = document.createElement("div");
    withdrawals.className = "list";
    for (const row of data.withdrawals || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${money(row.amount_usd)}</span><span class="rate">${statusLabel(row.status)}</span></div>
        <div class="muted">${row.payout_currency} payout - ${row.id}</div>
        ${row.notes ? `<div class="note">${row.notes}</div>` : ""}
      `;
      item.append(adminWithdrawalActions(row));
      withdrawals.append(item);
    }
    if (!withdrawals.children.length) withdrawals.append(emptyLine("No open withdrawals."));
    content.append(withdrawals);

    const missingTitle = document.createElement("div");
    missingTitle.className = "section-title";
    missingTitle.innerHTML = "<h2>Missing Pricing</h2>";
    content.append(missingTitle);
    const missing = document.createElement("div");
    missing.className = "list";
    for (const row of data.missing_pricing || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand} ${row.denomination} ${row.currency}</span><span class="rate">${row.region}</span></div>
        <div class="muted">Requested ${row.seen_count} time(s) - user ${row.created_by_user_id}</div>
      `;
      item.append(adminMissingPricingActions(row));
      missing.append(item);
    }
    if (!missing.children.length) missing.append(emptyLine("No missing pricing rows."));
    content.append(missing);

    const batchableTitle = document.createElement("div");
    batchableTitle.className = "section-title";
    batchableTitle.innerHTML = "<h2>Batchable Cards</h2>";
    content.append(batchableTitle);
    const batchable = document.createElement("div");
    batchable.className = "list";
    for (const row of data.batchable_cards || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand} ${row.denomination} ${row.currency}</span><span class="rate">${money(row.trader_value_usd)}</span></div>
        <div class="muted">${row.region} - ${statusLabel(row.status)} - ${row.id}</div>
        <div class="note">Code: ${row.code}${row.pin ? ` | PIN: ${row.pin}` : ""}</div>
      `;
      batchable.append(item);
    }
    if (!batchable.children.length) batchable.append(emptyLine("No cards ready for trader batching."));
    content.append(batchable);

    const traderTitle = document.createElement("div");
    traderTitle.className = "section-title";
    traderTitle.innerHTML = "<h2>Traders</h2>";
    traderTitle.append(button("primary", "Add trader", createTrader));
    content.append(traderTitle);
    const traders = document.createElement("div");
    traders.className = "list";
    for (const row of data.traders || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.name}</span><span class="rate">${statusLabel(row.status)}</span></div>
        <div class="muted">${row.default_currency} - ${row.id}</div>
        ${row.notes ? `<div class="note">${row.notes}</div>` : ""}
      `;
      item.append(adminTraderActions(row));
      traders.append(item);
    }
    if (!traders.children.length) traders.append(emptyLine("No traders yet."));
    content.append(traders);

    const auditTitle = document.createElement("div");
    auditTitle.className = "section-title";
    auditTitle.innerHTML = "<h2>Audit Logs</h2>";
    content.append(auditTitle);
    const audit = document.createElement("div");
    audit.className = "list";
    for (const row of data.audit_logs || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${statusLabel(row.action)}</span><span class="rate">${row.actor_user_id}</span></div>
        <div class="muted">${row.entity_type}:${row.entity_id}</div>
      `;
      audit.append(item);
    }
    if (!audit.children.length) audit.append(emptyLine("No audit logs yet."));
    content.append(audit);
  } catch (err) {
    clear();
    setError("Could not load admin queue.");
  }
}

function emptyLine(text) {
  const item = document.createElement("article");
  item.className = "rule";
  item.textContent = text;
  return item;
}

function openModal() {
  priceForm.reset();
  if (state.brand) priceForm.elements.brand.value = state.brand;
  if (state.regionKey) {
    const [region, currency] = state.regionKey.split("|");
    priceForm.elements.region.value = region || "";
    priceForm.elements.currency.value = currency || "USD";
  }
  modal.classList.remove("hidden");
}

function closePriceModal() {
  modal.classList.add("hidden");
}

function firstRuleValue(row) {
  if (row.range_min) return row.range_min;
  if (Array.isArray(row.denominations) && row.denominations.length) return row.denominations[0];
  const match = String(row.label || "").match(/\d+(?:\.\d+)?/);
  return match ? match[0] : "";
}

async function refreshQuote() {
  const body = Object.fromEntries(new FormData(sellForm).entries());
  if (!body.brand || !body.denomination) return;
  try {
    const data = await api("/mini/cardex/api/quote", { method: "POST", body: JSON.stringify(body) });
    const quote = data.quote || {};
    if (!quote.configured) {
      quoteBox.textContent = "No price is configured for this value.";
      quoteBox.classList.remove("hidden");
      return;
    }
    const amount = Number(quote.customer_value_usd || 0).toFixed(2);
    quoteBox.textContent = `Expected payout: $${amount} (${quote.customer_buy_rate_percent}%)`;
    quoteBox.classList.remove("hidden");
  } catch (err) {
    quoteBox.textContent = "Could not quote this value.";
    quoteBox.classList.remove("hidden");
  }
}

function openSellModal(row) {
  sellForm.reset();
  sellForm.elements.brand.value = row.brand || state.brand || "";
  sellForm.elements.region.value = row.region || "";
  sellForm.elements.currency.value = row.currency || "USD";
  sellForm.elements.denomination.value = firstRuleValue(row);
  sellSummary.textContent = `${row.brand} - ${row.region} - ${row.label} ${row.currency}`;
  quoteBox.classList.add("hidden");
  sellModal.classList.remove("hidden");
  refreshQuote();
}

function closeCardSellModal() {
  sellModal.classList.add("hidden");
}

function openWithdrawModal() {
  withdrawForm.reset();
  withdrawModal.classList.remove("hidden");
}

function closeWithdrawalModal() {
  withdrawModal.classList.add("hidden");
}

async function deleteRule(id) {
  if (!confirm("Delete this price category?")) return;
  await api(`/mini/cardex/api/prices/${encodeURIComponent(id)}`, { method: "DELETE" });
  await loadPrices();
  if (state.brand && state.regionKey) renderRules(state.brand, state.regionKey);
}

async function updateAdminCard(id, action) {
  openAdminForm({
    title: `${statusLabel(action)} card`,
    subtitle: id,
    submitText: statusLabel(action),
    fields: [{ name: "notes", label: "Notes", type: "textarea", placeholder: "Optional" }],
    onSubmit: async (body) => {
      await api(`/mini/cardex/api/admin/cards/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ action, notes: body.notes || "" }) });
      await renderAdmin();
    },
  });
}

async function updateAdminWithdrawal(id, action) {
  openAdminForm({
    title: `${statusLabel(action)} withdrawal`,
    subtitle: id,
    submitText: statusLabel(action),
    fields: [{ name: "notes", label: "Notes", type: "textarea", placeholder: "Optional" }],
    onSubmit: async (body) => {
      await api(`/mini/cardex/api/admin/withdrawals/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ action, notes: body.notes || "" }) });
      await renderAdmin();
    },
  });
}

async function setMissingPricing(row) {
  openAdminForm({
    title: "Set missing price",
    subtitle: `${row.brand} ${row.denomination} ${row.currency} - ${row.region}`,
    submitText: "Save price",
    fields: [
      { name: "customer_rate", label: "Customer rate %", required: true, inputmode: "decimal", placeholder: "80" },
      { name: "trader_rate", label: "Trader rate %", inputmode: "decimal", placeholder: "78" },
      { name: "note", label: "Public note", placeholder: "Optional" },
    ],
    onSubmit: async (body) => {
      await api(`/mini/cardex/api/admin/missing-pricing/${encodeURIComponent(row.id)}`, {
        method: "POST",
        body: JSON.stringify({ ...body, trader_rate: body.trader_rate || body.customer_rate }),
      });
      await loadPrices();
      await renderAdmin();
    },
  });
}

async function createTrader() {
  openAdminForm({
    title: "Add trader",
    submitText: "Create trader",
    fields: [
      { name: "name", label: "Trader name", required: true, placeholder: "Trader name" },
      { name: "notes", label: "Notes", type: "textarea", placeholder: "Optional" },
    ],
    onSubmit: async (body) => {
      await api("/mini/cardex/api/admin/traders", { method: "POST", body: JSON.stringify(body) });
      await renderAdmin();
    },
  });
}

async function recordTraderPayment(row) {
  openAdminForm({
    title: "Record trader payment",
    subtitle: row.name,
    submitText: "Record payment",
    fields: [
      { name: "amount_usd", label: "Amount USD", required: true, inputmode: "decimal", placeholder: "100" },
      { name: "method", label: "Method", placeholder: "Cash / USDT / bank" },
      { name: "reference_no", label: "Reference", placeholder: "Optional" },
      { name: "notes", label: "Notes", type: "textarea", placeholder: "Optional" },
    ],
    onSubmit: async (body) => {
      await api(`/mini/cardex/api/admin/traders/${encodeURIComponent(row.id)}/payments`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      window.setTimeout(() => showTraderStatement(row), 0);
    },
  });
}

async function createTraderBatch(row) {
  openAdminForm({
    title: "Batch cards",
    subtitle: row.name,
    submitText: "Create batch",
    fields: [
      { name: "card_ids", label: "Card IDs", type: "textarea", required: true, placeholder: "Paste IDs separated by commas or new lines" },
      { name: "notes", label: "Batch notes", type: "textarea", placeholder: "Optional" },
    ],
    onSubmit: async (body) => {
      const data = await api(`/mini/cardex/api/admin/traders/${encodeURIComponent(row.id)}/batches`, {
        method: "POST",
        body: JSON.stringify({ ...body, mark_sent: true }),
      });
      const batch = data.batch || {};
      await renderAdmin();
      window.setTimeout(() => {
        openAdminInfo({
          title: "Batch created",
          subtitle: row.name,
          text: `Reference: ${batch.id}\nCards: ${batch.total_count}\nExpected: ${money(batch.total_expected_from_trader_usd)}\nProfit: ${money(batch.gross_profit_usd)}`,
        });
      }, 0);
    },
  });
}

async function showTraderStatement(row) {
  try {
    const data = await api(`/mini/cardex/api/admin/traders/${encodeURIComponent(row.id)}/statement`);
    const lines = (data.statement || []).map((item) => {
      return `${statusLabel(item.entry_type)} | debit ${money(item.debit_usd)} | credit ${money(item.credit_usd)} | balance ${money(item.running_balance_usd)}`;
    });
    openAdminInfo({ title: "Trader statement", subtitle: row.name, text: lines.length ? lines.join("\n") : "No statement entries." });
  } catch (err) {
    openAdminInfo({ title: "Trader statement", subtitle: row.name, text: "Could not load trader statement." });
  }
}

priceForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withSubmitLock(priceForm, "Saving...", async () => {
    const form = new FormData(priceForm);
    const body = Object.fromEntries(form.entries());
    try {
      await api("/mini/cardex/api/prices", { method: "POST", body: JSON.stringify(body) });
      closePriceModal();
      await loadPrices();
    } catch (err) {
      setError("Could not save category. Check values.");
    }
  });
});

sellForm.elements.denomination.addEventListener("input", () => {
  window.clearTimeout(sellForm._quoteTimer);
  sellForm._quoteTimer = window.setTimeout(refreshQuote, 250);
});

sellForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withSubmitLock(sellForm, "Submitting...", async () => {
    const body = Object.fromEntries(new FormData(sellForm).entries());
    try {
      const data = await api("/mini/cardex/api/submit", { method: "POST", body: JSON.stringify(body) });
      if (data.missing_pricing) {
        closeCardSellModal();
        setNotice("This value has no price yet. Admin was notified.");
        return;
      }
      const amount = Number(data.quote?.customer_value_usd || 0).toFixed(2);
      closeCardSellModal();
      setNotice(`Card submitted. Expected payout: $${amount}`);
    } catch (err) {
      setError("Could not submit card. Check the value and code.");
    }
  });
});

withdrawForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withSubmitLock(withdrawForm, "Sending...", async () => {
    const body = Object.fromEntries(new FormData(withdrawForm).entries());
    try {
      const data = await api("/mini/cardex/api/withdrawals", { method: "POST", body: JSON.stringify(body) });
      closeWithdrawalModal();
      await renderWithdrawals();
      setNotice(`Withdrawal request created: ${data.withdrawal?.id || ""}`);
    } catch (err) {
      setError("Could not create withdrawal. Check available balance and payout details.");
    }
  });
});

closeModal.addEventListener("click", closePriceModal);
modal.addEventListener("click", (event) => {
  if (event.target?.dataset?.close) closePriceModal();
});
closeSellModal.addEventListener("click", closeCardSellModal);
sellModal.addEventListener("click", (event) => {
  if (event.target?.dataset?.closeSell) closeCardSellModal();
});
closeWithdrawModal.addEventListener("click", closeWithdrawalModal);
withdrawModal.addEventListener("click", (event) => {
  if (event.target?.dataset?.closeWithdraw) closeWithdrawalModal();
});
closeAdminFormModal.addEventListener("click", closeAdminForm);
adminFormModal.addEventListener("click", (event) => {
  if (event.target?.dataset?.closeAdminForm) closeAdminForm();
});
adminForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!adminFormHandler) return;
  await withSubmitLock(adminForm, "Saving...", async () => {
    const body = Object.fromEntries(new FormData(adminForm).entries());
    try {
      await adminFormHandler(body);
      closeAdminForm();
    } catch (err) {
      setError("Could not complete this admin action.");
    }
  });
});
refreshBtn.addEventListener("click", () => {
  if (state.view === "mycards") renderMyCards();
  else if (state.view === "wallet") renderWallet();
  else if (state.view === "withdrawals") renderWithdrawals();
  else if (state.view === "admin") renderAdmin();
  else loadPrices();
});
pricesTab.addEventListener("click", loadPrices);
cardsTab.addEventListener("click", renderMyCards);
walletTab.addEventListener("click", renderWallet);
withdrawTab.addEventListener("click", renderWithdrawals);
adminTab.addEventListener("click", renderAdmin);
searchInput.addEventListener("input", () => {
  state.search = searchInput.value || "";
  if (state.view === "brands") renderBrands();
  else if (state.view === "regions") renderRegions(state.brand);
  else if (state.view === "rules") renderRules(state.brand, state.regionKey);
});

loadPrices();
