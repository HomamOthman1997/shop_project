import { useState, useCallback } from 'react';
import { ChevronDown, RefreshCw } from 'lucide-react';
import useSWR from 'swr';
import { clsx } from 'clsx';
import { useAppStore, usePurchaseStore } from '@/stores';
import { Header, ScreenContainer } from '@/components/layout';
import { IconButton, toast } from '@/components/ui';
import { ServiceSelector, CountrySelector, StateSelector } from './Selectors';
import { QuoteList, ModeTabs } from './QuoteList';
import { fetchQuotes, fetchCountrySuggestions, purchaseNumber, haptic } from '@/api/client';
import type { ProviderQuote } from '@/types';

type SelectorView = 'none' | 'service' | 'country' | 'state';

export function PurchaseScreen() {
  const {
    getModes,
    getServiceById,
    getCountryByCode,
    selectedMode,
    selectedService,
    selectedCountry,
    selectedState,
    setSelectedMode,
    setSelectedService,
    setSelectedCountry,
    setSelectedState,
    setScreen,
  } = useAppStore();

  const { isPurchasing, setIsPurchasing, setPurchaseError } = usePurchaseStore();
  
  const [selectorView, setSelectorView] = useState<SelectorView>('none');
  const [purchasingToken, setPurchasingToken] = useState<string | null>(null);

  const modes = getModes();
  const selectedServiceData = getServiceById(selectedService);
  const selectedCountryData = getCountryByCode(selectedCountry);

  // Fetch country suggestions
  const { data: suggestions } = useSWR(
    selectedMode && selectedService ? ['suggestions', selectedMode, selectedService] : null,
    () => fetchCountrySuggestions(selectedMode, selectedService),
    { revalidateOnFocus: false }
  );

  // Fetch quotes
  const {
    data: quotesData,
    isLoading: isLoadingQuotes,
    mutate: refreshQuotes,
  } = useSWR(
    selectedMode && selectedService && selectedCountry
      ? ['quotes', selectedMode, selectedService, selectedCountry, selectedState]
      : null,
    () => fetchQuotes(selectedMode, selectedService, selectedCountry, selectedState),
    { revalidateOnFocus: false }
  );

  const quotes: ProviderQuote[] = quotesData?.providers || [];

  // Show state selector for US when in voice mode or when country has states
  const showStateSelector = selectedCountry === '1' && (selectedMode === 'voice' || selectedMode === 'rental');

  // Handle purchase
  const handlePurchase = useCallback(async (quoteToken: string) => {
    setIsPurchasing(true);
    setPurchasingToken(quoteToken);
    setPurchaseError(null);

    try {
      await purchaseNumber(quoteToken);
      haptic('success');
      toast.success('تم الشراء بنجاح');
      // Navigate to orders screen
      setScreen('orders');
    } catch (error) {
      haptic('error');
      const message = error instanceof Error ? error.message : 'فشل الشراء';
      toast.error(message);
      setPurchaseError(message);
    } finally {
      setIsPurchasing(false);
      setPurchasingToken(null);
    }
  }, [setIsPurchasing, setPurchaseError, setScreen]);

  // Refresh quotes
  const handleRefresh = () => {
    haptic('light');
    refreshQuotes();
  };

  return (
    <>
      <ScreenContainer
        header={
          <Header
            title="شراء رقم"
            subtitle={selectedServiceData?.name}
            action={
              <IconButton onClick={handleRefresh} disabled={isLoadingQuotes}>
                <RefreshCw className={clsx('w-5 h-5', isLoadingQuotes && 'animate-spin')} />
              </IconButton>
            }
          />
        }
      >
        <div className="space-y-4">
          {/* Mode Tabs */}
          {modes.length > 0 && (
            <ModeTabs
              modes={modes.map((m) => ({ key: m.key, label: m.label }))}
              selectedMode={selectedMode}
              onSelect={setSelectedMode}
            />
          )}

          {/* Selection Cards */}
          <div className="space-y-2">
            {/* Service Selector */}
            <button
              onClick={() => setSelectorView('service')}
              className="w-full flex items-center justify-between p-4 bg-card rounded-xl border border-border hover:bg-muted transition-colors"
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                  {selectedServiceData?.icon || (
                    <span className="text-primary font-bold">
                      {selectedServiceData?.name?.charAt(0) || '?'}
                    </span>
                  )}
                </div>
                <div className="text-right">
                  <p className="text-xs text-muted-foreground">الخدمة</p>
                  <p className="font-medium">{selectedServiceData?.name || 'اختر الخدمة'}</p>
                </div>
              </div>
              <ChevronDown className="w-5 h-5 text-muted-foreground" />
            </button>

            {/* Country Selector */}
            <button
              onClick={() => setSelectorView('country')}
              className="w-full flex items-center justify-between p-4 bg-card rounded-xl border border-border hover:bg-muted transition-colors"
            >
              <div className="flex items-center gap-3">
                <span className="text-2xl">{selectedCountryData?.flag || '🌍'}</span>
                <div className="text-right">
                  <p className="text-xs text-muted-foreground">الدولة</p>
                  <p className="font-medium">{selectedCountryData?.name || 'اختر الدولة'}</p>
                </div>
              </div>
              <ChevronDown className="w-5 h-5 text-muted-foreground" />
            </button>

            {/* State Selector (US only) */}
            {showStateSelector && (
              <button
                onClick={() => setSelectorView('state')}
                className="w-full flex items-center justify-between p-4 bg-card rounded-xl border border-border hover:bg-muted transition-colors"
              >
                <div className="text-right">
                  <p className="text-xs text-muted-foreground">الولاية</p>
                  <p className="font-medium">
                    {selectedState === 'none' ? 'بدون تحديد' : selectedState}
                  </p>
                </div>
                <ChevronDown className="w-5 h-5 text-muted-foreground" />
              </button>
            )}
          </div>

          {/* Quotes List */}
          {selectedService && selectedCountry && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-3">
                الأسعار المتاحة
              </h3>
              <QuoteList
                quotes={quotes}
                isLoading={isLoadingQuotes}
                mode={selectedMode}
                onPurchase={handlePurchase}
                isPurchasing={isPurchasing}
                purchasingToken={purchasingToken}
              />
            </div>
          )}
        </div>
      </ScreenContainer>

      {/* Selectors */}
      {selectorView === 'service' && (
        <ServiceSelector
          onSelect={setSelectedService}
          onClose={() => setSelectorView('none')}
        />
      )}
      {selectorView === 'country' && (
        <CountrySelector
          onSelect={setSelectedCountry}
          onClose={() => setSelectorView('none')}
          suggestions={suggestions}
        />
      )}
      {selectorView === 'state' && (
        <StateSelector
          onSelect={setSelectedState}
          onClose={() => setSelectorView('none')}
        />
      )}
    </>
  );
}
