import type {
  BootstrapData,
  QuoteResponse,
  Order,
  Account,
  RechargeData,
  SupportData,
  CountrySuggestion,
  ApiResponse,
} from '@/types';

// Telegram WebApp interface
declare global {
  interface Window {
    Telegram?: {
      WebApp: {
        initData: string;
        initDataUnsafe: {
          user?: {
            id: number;
            first_name: string;
            last_name?: string;
            username?: string;
            language_code?: string;
          };
        };
        ready: () => void;
        expand: () => void;
        close: () => void;
        MainButton: {
          text: string;
          color: string;
          textColor: string;
          isVisible: boolean;
          isActive: boolean;
          show: () => void;
          hide: () => void;
          enable: () => void;
          disable: () => void;
          showProgress: (leaveActive?: boolean) => void;
          hideProgress: () => void;
          onClick: (callback: () => void) => void;
          offClick: (callback: () => void) => void;
          setText: (text: string) => void;
        };
        BackButton: {
          isVisible: boolean;
          show: () => void;
          hide: () => void;
          onClick: (callback: () => void) => void;
          offClick: (callback: () => void) => void;
        };
        HapticFeedback: {
          impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
          notificationOccurred: (type: 'error' | 'success' | 'warning') => void;
          selectionChanged: () => void;
        };
        showAlert: (message: string, callback?: () => void) => void;
        showConfirm: (message: string, callback?: (confirmed: boolean) => void) => void;
        showPopup: (params: {
          title?: string;
          message: string;
          buttons?: Array<{ id?: string; type?: string; text?: string }>;
        }, callback?: (buttonId: string) => void) => void;
        themeParams: {
          bg_color?: string;
          text_color?: string;
          hint_color?: string;
          link_color?: string;
          button_color?: string;
          button_text_color?: string;
          secondary_bg_color?: string;
        };
        colorScheme: 'light' | 'dark';
        viewportHeight: number;
        viewportStableHeight: number;
        isExpanded: boolean;
        platform: string;
        version: string;
      };
    };
  }
}

const API_BASE = '/mini/numbers/api';

// Get Telegram initData for authentication
function getInitData(): string {
  return window.Telegram?.WebApp?.initData || '';
}

// Generic fetch wrapper with auth
async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const initData = getInitData();
  
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(initData && { 'X-Telegram-Init-Data': initData }),
    ...options.headers,
  };

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: 'Network error' }));
    throw new Error(error.message || `HTTP ${response.status}`);
  }

  return response.json();
}

// Bootstrap - Get initial app data
export async function fetchBootstrap(): Promise<BootstrapData> {
  return apiFetch<BootstrapData>('/bootstrap');
}

// Country Suggestions
export async function fetchCountrySuggestions(
  mode: string,
  service: string,
  limit = 10
): Promise<CountrySuggestion[]> {
  const params = new URLSearchParams({ mode, service, limit: String(limit) });
  const response = await apiFetch<ApiResponse & { countries: CountrySuggestion[] }>(
    `/country-suggestions?${params}`
  );
  if (!response.ok) {
    throw new Error(response.message || 'Failed to load country suggestions');
  }
  return response.countries;
}

// Quotes/Prices
export async function fetchQuotes(
  mode: string,
  service: string,
  country: string,
  state?: string
): Promise<QuoteResponse> {
  const params = new URLSearchParams({ mode, service, country });
  if (state && state !== 'none') {
    params.set('state', state);
  }
  const response = await apiFetch<QuoteResponse>(`/prices?${params}`);
  if (!response.ok) {
    throw new Error((response as ApiResponse).message || 'Failed to load prices');
  }
  return response;
}

// Purchase
export async function purchaseNumber(
  quoteToken: string,
  language: string = 'ar'
): Promise<Order> {
  const response = await apiFetch<ApiResponse & { order: Order }>('/purchase', {
    method: 'POST',
    body: JSON.stringify({ quote_token: quoteToken, language }),
  });
  if (!response.ok) {
    throw new Error(response.message || 'Purchase failed');
  }
  return response.order;
}

// Orders
export async function fetchOrders(
  mode: string = 'all',
  limit: number = 20
): Promise<Order[]> {
  const params = new URLSearchParams({ mode, limit: String(limit) });
  const response = await apiFetch<ApiResponse & { orders: Order[] }>(`/orders?${params}`);
  if (!response.ok) {
    throw new Error(response.message || 'Failed to load orders');
  }
  return response.orders;
}

export async function fetchOrder(orderId: string): Promise<Order> {
  const response = await apiFetch<ApiResponse & { order: Order }>(`/orders/${orderId}`);
  if (!response.ok) {
    throw new Error(response.message || 'Failed to load order');
  }
  return response.order;
}

// Order Actions
export async function refreshOrder(orderId: string): Promise<Order> {
  const response = await apiFetch<ApiResponse & { order: Order }>(
    `/orders/${orderId}/refresh`,
    { method: 'POST' }
  );
  if (!response.ok) {
    throw new Error(response.message || 'Refresh failed');
  }
  return response.order;
}

export async function resendCode(orderId: string): Promise<Order> {
  const response = await apiFetch<ApiResponse & { order: Order }>(
    `/orders/${orderId}/second-code`,
    { method: 'POST' }
  );
  if (!response.ok) {
    throw new Error(response.message || 'Resend failed');
  }
  return response.order;
}

export async function replaceOrder(orderId: string): Promise<Order> {
  const response = await apiFetch<ApiResponse & { order: Order }>(
    `/orders/${orderId}/replace`,
    { method: 'POST' }
  );
  if (!response.ok) {
    throw new Error(response.message || 'Replace failed');
  }
  return response.order;
}

export async function alternateProvider(orderId: string): Promise<Order> {
  const response = await apiFetch<ApiResponse & { order: Order }>(
    `/orders/${orderId}/alternate`,
    { method: 'POST' }
  );
  if (!response.ok) {
    throw new Error(response.message || 'Alternate provider failed');
  }
  return response.order;
}

// Rental Actions
export async function fetchRentalSms(orderId: string): Promise<{ messages: string[]; order: Order }> {
  const response = await apiFetch<ApiResponse & { messages: string[]; order: Order }>(
    `/orders/${orderId}/rental/sms`,
    { method: 'POST' }
  );
  if (!response.ok) {
    throw new Error(response.message || 'Failed to fetch SMS');
  }
  return { messages: response.messages, order: response.order };
}

export async function finishRental(orderId: string): Promise<Order> {
  const response = await apiFetch<ApiResponse & { order: Order }>(
    `/orders/${orderId}/rental/finish`,
    { method: 'POST' }
  );
  if (!response.ok) {
    throw new Error(response.message || 'Finish failed');
  }
  return response.order;
}

export async function renewRental(orderId: string): Promise<Order> {
  const response = await apiFetch<ApiResponse & { order: Order }>(
    `/orders/${orderId}/rental/renew`,
    { method: 'POST' }
  );
  if (!response.ok) {
    throw new Error(response.message || 'Renew failed');
  }
  return response.order;
}

export async function wakeRental(orderId: string): Promise<Order> {
  const response = await apiFetch<ApiResponse & { order: Order }>(
    `/orders/${orderId}/rental/wake`,
    { method: 'POST' }
  );
  if (!response.ok) {
    throw new Error(response.message || 'Wake failed');
  }
  return response.order;
}

// Account
export async function fetchAccount(): Promise<Account> {
  const response = await apiFetch<ApiResponse & Account>('/account');
  if (!response.ok) {
    throw new Error(response.message || 'Failed to load account');
  }
  return response;
}

export async function updateLanguage(language: string): Promise<void> {
  const response = await apiFetch<ApiResponse>('/account/language', {
    method: 'POST',
    body: JSON.stringify({ language }),
  });
  if (!response.ok) {
    throw new Error(response.message || 'Failed to update language');
  }
}

// Recharge
export async function fetchRecharge(): Promise<RechargeData> {
  const response = await apiFetch<ApiResponse & RechargeData>('/recharge');
  if (!response.ok) {
    throw new Error(response.message || 'Failed to load recharge options');
  }
  return response;
}

// Support
export async function fetchSupport(): Promise<SupportData> {
  const response = await apiFetch<ApiResponse & SupportData>('/support');
  if (!response.ok) {
    throw new Error(response.message || 'Failed to load support options');
  }
  return response;
}

// Telegram Haptic Feedback helper
export function haptic(type: 'success' | 'error' | 'warning' | 'light' | 'medium' | 'heavy' | 'selection') {
  const tg = window.Telegram?.WebApp;
  if (!tg?.HapticFeedback) return;
  
  switch (type) {
    case 'success':
    case 'error':
    case 'warning':
      tg.HapticFeedback.notificationOccurred(type);
      break;
    case 'selection':
      tg.HapticFeedback.selectionChanged();
      break;
    default:
      tg.HapticFeedback.impactOccurred(type);
  }
}
