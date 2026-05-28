import { clsx } from 'clsx';
import { Search, X, Star, ChevronLeft } from 'lucide-react';
import { useState, useMemo } from 'react';
import { useAppStore } from '@/stores';
import { haptic } from '@/api/client';
import type { Service, Country, USState } from '@/types';

interface SearchableListProps<T> {
  items: T[];
  selectedId: string;
  onSelect: (id: string) => void;
  renderItem: (item: T, isSelected: boolean) => React.ReactNode;
  getItemId: (item: T) => string;
  getSearchText: (item: T) => string;
  placeholder: string;
  emptyMessage: string;
}

function SearchableList<T>({
  items,
  selectedId,
  onSelect,
  renderItem,
  getItemId,
  getSearchText,
  placeholder,
  emptyMessage,
}: SearchableListProps<T>) {
  const [search, setSearch] = useState('');

  const filteredItems = useMemo(() => {
    if (!search.trim()) return items;
    const searchLower = search.toLowerCase();
    return items.filter((item) =>
      getSearchText(item).toLowerCase().includes(searchLower)
    );
  }, [items, search, getSearchText]);

  return (
    <div className="flex flex-col h-full">
      {/* Search Input */}
      <div className="relative px-4 py-3 border-b border-border">
        <Search className="absolute right-7 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={placeholder}
          className="w-full bg-muted rounded-xl py-2.5 pr-10 pl-4 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            className="absolute left-7 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-2">
        {filteredItems.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
            {emptyMessage}
          </div>
        ) : (
          <div className="space-y-1">
            {filteredItems.map((item) => {
              const id = getItemId(item);
              const isSelected = id === selectedId;
              return (
                <button
                  key={id}
                  onClick={() => {
                    haptic('selection');
                    onSelect(id);
                  }}
                  className={clsx(
                    'w-full text-right transition-all duration-200 rounded-xl',
                    isSelected && 'bg-primary/10'
                  )}
                >
                  {renderItem(item, isSelected)}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// Service Selector
interface ServiceSelectorProps {
  onSelect: (serviceId: string) => void;
  onClose: () => void;
}

export function ServiceSelector({ onSelect, onClose }: ServiceSelectorProps) {
  const { getServices, selectedService } = useAppStore();
  const services = getServices();

  // Separate popular services
  const popularServices = services.filter((s) => s.popular);
  const otherServices = services.filter((s) => !s.popular);

  return (
    <div className="fixed inset-0 z-50 bg-background flex flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-3 border-b border-border">
        <button onClick={onClose} className="p-2 -mr-2 hover:bg-muted rounded-lg">
          <ChevronLeft className="w-5 h-5" />
        </button>
        <h2 className="text-lg font-semibold">اختر الخدمة</h2>
      </header>

      <SearchableList
        items={[...popularServices, ...otherServices]}
        selectedId={selectedService}
        onSelect={(id) => {
          onSelect(id);
          onClose();
        }}
        getItemId={(s) => s.id}
        getSearchText={(s) => s.name}
        placeholder="ابحث عن الخدمة..."
        emptyMessage="لا توجد نتائج"
        renderItem={(service: Service, isSelected) => (
          <div className={clsx(
            'flex items-center gap-3 p-3',
            isSelected ? 'text-primary' : 'text-foreground'
          )}>
            <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center text-lg">
              {service.icon || service.name.charAt(0)}
            </div>
            <span className="flex-1 font-medium">{service.name}</span>
            {service.popular && (
              <Star className="w-4 h-4 text-warning fill-warning" />
            )}
          </div>
        )}
      />
    </div>
  );
}

// Country Selector
interface CountrySelectorProps {
  onSelect: (countryCode: string) => void;
  onClose: () => void;
  suggestions?: { code: string; name: string; price_label: string }[];
}

export function CountrySelector({ onSelect, onClose, suggestions }: CountrySelectorProps) {
  const { getCountries, selectedCountry } = useAppStore();
  const countries = getCountries();

  return (
    <div className="fixed inset-0 z-50 bg-background flex flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-3 border-b border-border">
        <button onClick={onClose} className="p-2 -mr-2 hover:bg-muted rounded-lg">
          <ChevronLeft className="w-5 h-5" />
        </button>
        <h2 className="text-lg font-semibold">اختر الدولة</h2>
      </header>

      {/* Suggestions */}
      {suggestions && suggestions.length > 0 && (
        <div className="px-4 py-3 border-b border-border">
          <p className="text-xs text-muted-foreground mb-2">مقترحات</p>
          <div className="flex flex-wrap gap-2">
            {suggestions.slice(0, 5).map((s) => (
              <button
                key={s.code}
                onClick={() => {
                  haptic('selection');
                  onSelect(s.code);
                  onClose();
                }}
                className={clsx(
                  'px-3 py-1.5 rounded-full text-sm font-medium transition-colors',
                  selectedCountry === s.code
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-foreground hover:bg-muted/80'
                )}
              >
                {s.name} - {s.price_label}
              </button>
            ))}
          </div>
        </div>
      )}

      <SearchableList
        items={countries}
        selectedId={selectedCountry}
        onSelect={(code) => {
          onSelect(code);
          onClose();
        }}
        getItemId={(c) => c.code}
        getSearchText={(c) => c.name}
        placeholder="ابحث عن الدولة..."
        emptyMessage="لا توجد نتائج"
        renderItem={(country: Country, isSelected) => (
          <div className={clsx(
            'flex items-center gap-3 p-3',
            isSelected ? 'text-primary' : 'text-foreground'
          )}>
            <span className="text-2xl">{country.flag || '🌍'}</span>
            <span className="flex-1 font-medium">{country.name}</span>
            <span className="text-muted-foreground text-sm">+{country.code}</span>
          </div>
        )}
      />
    </div>
  );
}

// State Selector (US States)
interface StateSelectorProps {
  onSelect: (stateCode: string) => void;
  onClose: () => void;
}

export function StateSelector({ onSelect, onClose }: StateSelectorProps) {
  const { getUSStates, selectedState } = useAppStore();
  const states = getUSStates();

  return (
    <div className="fixed inset-0 z-50 bg-background flex flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-3 border-b border-border">
        <button onClick={onClose} className="p-2 -mr-2 hover:bg-muted rounded-lg">
          <ChevronLeft className="w-5 h-5" />
        </button>
        <h2 className="text-lg font-semibold">اختر الولاية</h2>
      </header>

      {/* None option */}
      <button
        onClick={() => {
          haptic('selection');
          onSelect('none');
          onClose();
        }}
        className={clsx(
          'mx-4 mt-3 p-3 rounded-xl text-right transition-colors',
          selectedState === 'none' ? 'bg-primary/10 text-primary' : 'bg-muted'
        )}
      >
        <span className="font-medium">بدون تحديد ولاية</span>
      </button>

      <SearchableList
        items={states}
        selectedId={selectedState}
        onSelect={(code) => {
          onSelect(code);
          onClose();
        }}
        getItemId={(s) => s.code}
        getSearchText={(s) => s.name}
        placeholder="ابحث عن الولاية..."
        emptyMessage="لا توجد نتائج"
        renderItem={(state: USState, isSelected) => (
          <div className={clsx(
            'flex items-center gap-3 p-3',
            isSelected ? 'text-primary' : 'text-foreground'
          )}>
            <span className="flex-1 font-medium">{state.name}</span>
            <span className="text-muted-foreground text-sm">{state.code}</span>
          </div>
        )}
      />
    </div>
  );
}
