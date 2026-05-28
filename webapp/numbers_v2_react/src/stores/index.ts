import { create } from 'zustand';
import type { Screen, BootstrapData, Service, Country, USState, Mode } from '@/types';

interface AppStore {
  // Navigation
  screen: Screen;
  setScreen: (screen: Screen) => void;
  
  // Bootstrap data
  bootstrap: BootstrapData | null;
  setBootstrap: (data: BootstrapData) => void;
  
  // Selection state
  selectedMode: string;
  selectedService: string;
  selectedCountry: string;
  selectedState: string;
  setSelectedMode: (mode: string) => void;
  setSelectedService: (service: string) => void;
  setSelectedCountry: (country: string) => void;
  setSelectedState: (state: string) => void;
  
  // Language
  language: string;
  setLanguage: (lang: string) => void;
  
  // Loading/Error states
  isInitializing: boolean;
  setIsInitializing: (loading: boolean) => void;
  globalError: string | null;
  setGlobalError: (error: string | null) => void;
  
  // Helpers
  getModes: () => Mode[];
  getServices: () => Service[];
  getCountries: () => Country[];
  getUSStates: () => USState[];
  getServiceById: (id: string) => Service | undefined;
  getCountryByCode: (code: string) => Country | undefined;
}

export const useAppStore = create<AppStore>((set, get) => ({
  // Navigation
  screen: 'purchase',
  setScreen: (screen) => set({ screen }),
  
  // Bootstrap data
  bootstrap: null,
  setBootstrap: (data) => set({ 
    bootstrap: data,
    selectedMode: data.default_mode || 'temp',
    selectedService: data.default_service || '',
    selectedCountry: data.default_country || '',
    selectedState: 'none',
  }),
  
  // Selection state
  selectedMode: 'temp',
  selectedService: '',
  selectedCountry: '',
  selectedState: 'none',
  setSelectedMode: (mode) => set({ selectedMode: mode }),
  setSelectedService: (service) => set({ selectedService: service }),
  setSelectedCountry: (country) => set({ selectedCountry: country, selectedState: 'none' }),
  setSelectedState: (state) => set({ selectedState: state }),
  
  // Language
  language: 'ar',
  setLanguage: (lang) => set({ language: lang }),
  
  // Loading/Error states
  isInitializing: true,
  setIsInitializing: (loading) => set({ isInitializing: loading }),
  globalError: null,
  setGlobalError: (error) => set({ globalError: error }),
  
  // Helpers
  getModes: () => get().bootstrap?.modes || [],
  getServices: () => get().bootstrap?.services || [],
  getCountries: () => get().bootstrap?.countries || [],
  getUSStates: () => get().bootstrap?.us_states || [],
  getServiceById: (id) => get().bootstrap?.services.find(s => s.id === id),
  getCountryByCode: (code) => get().bootstrap?.countries.find(c => c.code === code),
}));

// Purchase flow store
interface PurchaseStore {
  isLoadingQuotes: boolean;
  setIsLoadingQuotes: (loading: boolean) => void;
  isPurchasing: boolean;
  setIsPurchasing: (purchasing: boolean) => void;
  purchaseError: string | null;
  setPurchaseError: (error: string | null) => void;
}

export const usePurchaseStore = create<PurchaseStore>((set) => ({
  isLoadingQuotes: false,
  setIsLoadingQuotes: (loading) => set({ isLoadingQuotes: loading }),
  isPurchasing: false,
  setIsPurchasing: (purchasing) => set({ isPurchasing: purchasing }),
  purchaseError: null,
  setPurchaseError: (error) => set({ purchaseError: error }),
}));

// Orders store
interface OrdersStore {
  filterMode: string;
  setFilterMode: (mode: string) => void;
  refreshingOrderId: string | null;
  setRefreshingOrderId: (id: string | null) => void;
}

export const useOrdersStore = create<OrdersStore>((set) => ({
  filterMode: 'all',
  setFilterMode: (mode) => set({ filterMode: mode }),
  refreshingOrderId: null,
  setRefreshingOrderId: (id) => set({ refreshingOrderId: id }),
}));
