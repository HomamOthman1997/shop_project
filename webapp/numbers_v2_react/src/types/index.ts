// API Response Types
export interface ApiResponse<T = unknown> {
  ok: boolean;
  code?: string;
  message?: string;
  data?: T;
}

// Bootstrap Types
export interface BootstrapData {
  modes: Mode[];
  default_mode: string;
  default_service: string;
  default_country: string;
  services: Service[];
  countries: Country[];
  us_states: USState[];
  client: ClientConfig;
  api: ApiConfig;
}

export interface Mode {
  key: string;
  label: string;
  label_key: string;
}

export interface Service {
  id: string;
  name: string;
  icon?: string;
  popular?: boolean;
}

export interface Country {
  code: string;
  name: string;
  flag?: string;
  has_states?: boolean;
}

export interface USState {
  code: string;
  name: string;
}

export interface ClientConfig {
  tabs: Tab[];
  actions: Record<string, ClientAction>;
}

export interface Tab {
  key: string;
  label_key: string;
  icon: string;
  endpoint?: string;
}

export interface ClientAction {
  enabled: boolean;
  endpoint: string;
  method: string;
  reason?: string;
}

export interface ApiConfig {
  base_path: string;
  quote_ttl_sec: number;
  capabilities: Record<string, boolean | string[]>;
  actions: Record<string, ApiAction>;
}

export interface ApiAction {
  enabled?: boolean;
  endpoint: string;
  method: string;
  scope?: string;
  reason?: string;
  requires_idempotency_key?: boolean;
}

// Quote Types
export interface QuoteRequest {
  mode: string;
  service: string;
  country: string;
  state?: string;
}

export interface QuoteResponse {
  ok: boolean;
  mode: string;
  service: string;
  country: string;
  state?: string;
  providers: ProviderQuote[];
}

export interface ProviderQuote {
  provider_id: string;
  provider: string;
  price: number;
  price_label: string;
  quantity?: number;
  quote_token: string;
  purchase_action?: PurchaseAction;
  // Rental specific
  options?: RentalOption[];
}

export interface RentalOption {
  duration_label: string;
  price: number;
  price_label: string;
  quote_token: string;
  can_renew?: boolean;
  purchase_action?: PurchaseAction;
}

export interface PurchaseAction {
  enabled: boolean;
  label_key: string;
  endpoint: string;
  method: string;
  body?: Record<string, unknown>;
  reason?: string;
}

// Order Types
export interface Order {
  id: string;
  mode: 'temp' | 'rental' | 'voice';
  status: string;
  public_status: string;
  service: string;
  service_name: string;
  country: string;
  country_name: string;
  state?: string;
  number: string;
  number_formatted?: string;
  code?: string;
  codes?: string[];
  full_sms?: string;
  price: number;
  price_label: string;
  provider_id: string;
  provider: string;
  created_at: string;
  expires_at?: string;
  customer_state: CustomerState;
  actions: Record<string, OrderAction>;
  api_actions?: Record<string, ApiAction>;
  // Rental specific
  duration_label?: string;
  end_date?: string;
  notes?: string;
  tags?: string[];
  messages?: string[];
  can_finish?: boolean;
  can_renew?: boolean;
  can_wake?: boolean;
  can_notes?: boolean;
  // Voice specific
  calls_count?: number;
  recording_available?: boolean;
  recording_url?: string;
  // Refund
  refund?: OrderRefund;
}

export interface CustomerState {
  key: string;
  tone: 'waiting' | 'success' | 'pending-refund' | 'refunded' | 'danger';
  status_label_key: string;
  receive_label_key?: string;
  message_key?: string;
  recommended_action_key?: string;
  provider_reference?: string;
  show_provider_identity: boolean;
  awaiting_webhook: boolean;
  auto_refund_managed: boolean;
  manual_refund_available: boolean;
  support_review_open: boolean;
}

export interface OrderAction {
  enabled: boolean;
  label_key: string;
  endpoint?: string;
  method: 'POST' | 'GET' | 'CLIENT';
  reason?: string;
  confirm_label_key?: string;
  busy_label_key?: string;
  success_label_key?: string;
  idempotency_key?: string;
}

export interface OrderRefund {
  status: string;
  amount?: number;
  amount_label?: string;
  reason?: string;
}

// Account Types
export interface Account {
  user: User;
  reseller?: { id: number };
  wallet: Wallet;
  recent_activity: WalletActivity[];
}

export interface User {
  id: number;
  username?: string;
  language: string;
  joined_at: string;
}

export interface Wallet {
  balance: number;
  currency: string;
  balance_label: string;
}

export interface WalletActivity {
  id: string;
  kind: string;
  label: string;
  direction: 'credit' | 'debit';
  amount: number;
  amount_label: string;
  balance_after: number;
  balance_label: string;
  created_at: string;
  order_id?: string;
}

// Recharge Types
export interface RechargeData {
  wallet: Wallet;
  methods: PaymentMethod[];
  actions: Record<string, ClientAction>;
  capabilities: Record<string, boolean>;
}

export interface PaymentMethod {
  code: string;
  title: string;
  currency: string;
  target: string;
  support: string;
  rate: number;
  rate_label: string;
  instructions: string;
}

// Support Types
export interface SupportData {
  categories: SupportCategory[];
  actions: Record<string, ClientAction>;
  capabilities: Record<string, boolean>;
}

export interface SupportCategory {
  key: string;
  label: string;
}

// Country Suggestion
export interface CountrySuggestion {
  code: string;
  name: string;
  price: number;
  price_label: string;
}

// Translations
export type Translations = Record<string, string>;

// App State
export type Screen = 'purchase' | 'orders' | 'account' | 'recharge' | 'support';

export interface AppState {
  screen: Screen;
  language: string;
  isLoading: boolean;
  error: string | null;
}
