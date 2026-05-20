const tg = window.Telegram?.WebApp;
const state = {
  lang: "ar",
  mode: "temp",
  services: [],
  countries: [],
  states: [],
  selectedService: "telegram",
  selectedCountry: "none",
  selectedState: "none",
  loading: false,
};

const els = {
  modeSwitch: document.getElementById("modeSwitch"),
  serviceSearch: document.getElementById("serviceSearch"),
  servicesList: document.getElementById("servicesList"),
  countrySelect: document.getElementById("countrySelect"),
  stateSelect: document.getElementById("stateSelect"),
  stateField: document.getElementById("stateField"),
  quickServices: document.getElementById("quickServices"),
  quoteButton: document.getElementById("quoteButton"),
  providerList: document.getElementById("providerList"),
  statusLine: document.getElementById("statusLine"),
  resultCount: document.getElementById("resultCount"),
  selectionTitle: document.getElementById("selectionTitle"),
  sessionPill: document.getElementById("sessionPill"),
};

const copy = {
  ar: {
    eyebrow: "CyberZone Numbers",
    title: "الأرقام",
    service: "الخدمة",
    country: "الدولة",
    state: "الولاية",
    check: "فحص الأسعار",
    providers: "المزودين",
    loading: "جاري فحص المزودين",
    ready: "اختر الخدمة والدولة ثم افحص السعر",
    empty: "لا توجد عروض متاحة لهذا الاختيار",
    error: "تعذر تحميل الأسعار حاليا",
    temp: "أرقام مؤقتة",
    rental: "أرقام إيجار",
    voice: "رقم اتصال",
    success: "نجاح",
    base: "التكلفة",
    options: "خيارات",
    unavailable: "غير متاح",
  },
  en: {
    eyebrow: "CyberZone Numbers",
    title: "Numbers",
    service: "Service",
    country: "Country",
    state: "State",
    check: "Check prices",
    providers: "Providers",
    loading: "Checking providers",
    ready: "Choose a service and country, then check prices",
    empty: "No offers are available for this selection",
    error: "Could not load prices right now",
    temp: "Temporary SMS",
    rental: "Rental numbers",
    voice: "Call number",
    success: "Success",
    base: "Cost",
    options: "Options",
    unavailable: "Unavailable",
  },
};

function t(key) {
  return (copy[state.lang] || copy.en)[key] || copy.en[key] || key;
}

function setLanguage() {
  const languageCode = tg?.initDataUnsafe?.user?.language_code || navigator.language || "ar";
  state.lang = String(languageCode).toLowerCase().startsWith("ar") ? "ar" : "en";
  document.documentElement.lang = state.lang;
  document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  els.statusLine.textContent = t("ready");
}

function headers() {
  const initData = tg?.initData || "";
  return initData ? { "X-Telegram-Init-Data": initData } : {};
}

async function api(path) {
  const response = await fetch(path, { headers: headers(), cache: "no-store" });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function serviceLabel(key) {
  const found = state.services.find((item) => item.key === key);
  return found?.label || key;
}

function selectedServiceFromInput() {
  const raw = els.serviceSearch.value.trim();
  if (!raw) return state.selectedService;
  const lowered = raw.toLowerCase();
  const exact = state.services.find((item) => item.label.toLowerCase() === lowered || item.key.toLowerCase() === lowered);
  if (exact) return exact.key;
  const partial = state.services.find((item) => item.label.toLowerCase().includes(lowered) || item.key.toLowerCase().includes(lowered));
  return partial?.key || state.selectedService;
}

function renderModes() {
  const modes = [
    ["temp", t("temp")],
    ["rental", t("rental")],
    ["voice", t("voice")],
  ];
  els.modeSwitch.replaceChildren(
    ...modes.map(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `mode-button${state.mode === key ? " active" : ""}`;
      button.textContent = label;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", state.mode === key ? "true" : "false");
      button.addEventListener("click", () => {
        state.mode = key;
        renderModes();
      });
      return button;
    })
  );
}

function renderSelectors() {
  els.servicesList.replaceChildren(
    ...state.services.map((item) => {
      const option = document.createElement("option");
      option.value = item.label;
      option.dataset.key = item.key;
      return option;
    })
  );
  els.serviceSearch.value = serviceLabel(state.selectedService);

  els.countrySelect.replaceChildren(
    ...state.countries.map((item) => {
      const option = document.createElement("option");
      option.value = item.code;
      option.textContent = item.iso ? `${item.name} (${item.iso})` : item.name;
      return option;
    })
  );
  els.countrySelect.value = state.selectedCountry;

  els.stateSelect.replaceChildren(
    ...state.states.map((item) => {
      const option = document.createElement("option");
      option.value = item.code;
      option.textContent = item.name;
      return option;
    })
  );
  els.stateSelect.value = state.selectedState;
  updateStateVisibility();
}

function updateStateVisibility() {
  const showState = state.selectedCountry === "1" && state.mode !== "rental";
  els.stateField.classList.toggle("hidden", !showState);
  if (!showState) {
    state.selectedState = "none";
    els.stateSelect.value = "none";
  }
}

function renderQuickServices() {
  const top = state.services.filter((item) => item.top).slice(0, 10);
  els.quickServices.replaceChildren(
    ...top.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `quick-chip${state.selectedService === item.key ? " active" : ""}`;
      button.textContent = item.label;
      button.addEventListener("click", () => {
        state.selectedService = item.key;
        els.serviceSearch.value = item.label;
        renderQuickServices();
      });
      return button;
    })
  );
}

function setLoading(loading) {
  state.loading = loading;
  els.quoteButton.disabled = loading;
  els.quoteButton.textContent = loading ? t("loading") : t("check");
}

function renderProviders(rows) {
  els.resultCount.textContent = String(rows.length);
  if (!rows.length) {
    els.providerList.replaceChildren(emptyState(t("empty")));
    return;
  }
  els.providerList.replaceChildren(
    ...rows.map((row) => {
      const card = document.createElement("article");
      card.className = `provider-card${row.available ? "" : " unavailable"}`;

      const main = document.createElement("div");
      main.className = "provider-main";

      const name = document.createElement("p");
      name.className = "provider-name";
      const id = document.createElement("span");
      id.className = "provider-id";
      id.textContent = row.provider_id;
      name.append(id, document.createTextNode(row.provider));

      const meta = document.createElement("p");
      meta.className = "provider-meta";
      const details = [`${t("success")}: ${row.success_rate}`];
      if (row.base_price_label && row.base_price_label !== "-") details.push(`${t("base")}: ${row.base_price_label}`);
      if (!row.available && row.reason) details.push(row.reason);
      meta.textContent = details.join(" · ");

      main.append(name, meta);
      if (row.options?.length) {
        const options = document.createElement("div");
        options.className = "option-row";
        row.options.slice(0, 5).forEach((option) => {
          const pill = document.createElement("span");
          pill.className = "option-pill";
          pill.textContent = `${option.duration || t("options")} ${option.price_label}`;
          options.append(pill);
        });
        main.append(options);
      }

      const price = document.createElement("div");
      price.className = "provider-price";
      price.textContent = row.available ? row.price_label : t("unavailable");

      card.append(main, price);
      return card;
    })
  );
}

function emptyState(text) {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.textContent = text;
  return div;
}

async function checkPrices() {
  state.selectedService = selectedServiceFromInput();
  state.selectedCountry = els.countrySelect.value || "none";
  state.selectedState = els.stateSelect.value || "none";
  updateStateVisibility();
  renderQuickServices();
  els.selectionTitle.textContent = serviceLabel(state.selectedService);
  els.statusLine.textContent = t("loading");
  setLoading(true);
  try {
    const params = new URLSearchParams({
      mode: state.mode,
      service: state.selectedService,
      country: state.selectedCountry,
      state: state.selectedState,
    });
    const payload = await api(`/mini/numbers/api/prices?${params.toString()}`);
    els.statusLine.textContent = payload.ok === false ? payload.message || t("error") : "";
    renderProviders(payload.providers || []);
  } catch (error) {
    els.statusLine.textContent = t("error");
    renderProviders([]);
  } finally {
    setLoading(false);
  }
}

async function boot() {
  tg?.ready();
  tg?.expand();
  setLanguage();
  els.sessionPill.textContent = tg?.initDataUnsafe?.user?.first_name || "Mini App";
  const payload = await api("/mini/numbers/api/bootstrap");
  state.services = payload.services || [];
  state.countries = payload.countries || [];
  state.states = payload.states_us || [];
  state.selectedService = payload.defaults?.service || "telegram";
  state.selectedCountry = payload.defaults?.country || "none";
  state.selectedState = payload.defaults?.state || "none";
  renderModes();
  renderSelectors();
  renderQuickServices();
  renderProviders([]);
  els.countrySelect.addEventListener("change", () => {
    state.selectedCountry = els.countrySelect.value || "none";
    updateStateVisibility();
  });
  els.stateSelect.addEventListener("change", () => {
    state.selectedState = els.stateSelect.value || "none";
  });
  els.quoteButton.addEventListener("click", checkPrices);
}

boot().catch(() => {
  setLanguage();
  els.statusLine.textContent = t("error");
  renderProviders([]);
});
