import { clsx } from 'clsx';
import { Loader2, ShoppingCart } from 'lucide-react';
import { Button } from '@/components/ui';
import { QuoteCardSkeleton } from '@/components/ui/Skeleton';
import type { ProviderQuote, RentalOption } from '@/types';
import { haptic } from '@/api/client';

interface QuoteListProps {
  quotes: ProviderQuote[];
  isLoading: boolean;
  mode: string;
  onPurchase: (quoteToken: string) => void;
  isPurchasing: boolean;
  purchasingToken: string | null;
}

export function QuoteList({
  quotes,
  isLoading,
  mode,
  onPurchase,
  isPurchasing,
  purchasingToken,
}: QuoteListProps) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <QuoteCardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (quotes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
          <ShoppingCart className="w-8 h-8 text-muted-foreground" />
        </div>
        <p className="text-muted-foreground">لا تتوفر أرقام حالياً</p>
        <p className="text-sm text-muted-foreground mt-1">جرب خدمة أو دولة أخرى</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {quotes.map((quote, index) => (
        <QuoteCard
          key={`${quote.provider_id}-${index}`}
          quote={quote}
          mode={mode}
          onPurchase={onPurchase}
          isPurchasing={isPurchasing && purchasingToken === quote.quote_token}
          disabled={isPurchasing}
        />
      ))}
    </div>
  );
}

interface QuoteCardProps {
  quote: ProviderQuote;
  mode: string;
  onPurchase: (quoteToken: string) => void;
  isPurchasing: boolean;
  disabled: boolean;
}

function QuoteCard({ quote, mode, onPurchase, isPurchasing, disabled }: QuoteCardProps) {
  const handlePurchase = (token: string) => {
    haptic('medium');
    onPurchase(token);
  };

  // Rental mode has options
  if (mode === 'rental' && quote.options && quote.options.length > 0) {
    return (
      <div className="bg-card rounded-xl border border-border overflow-hidden">
        {/* Provider Header */}
        <div className="flex items-center gap-3 p-4 border-b border-border">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <span className="text-primary font-bold">{quote.provider.charAt(0)}</span>
          </div>
          <div className="flex-1">
            <p className="font-medium">{quote.provider}</p>
            {quote.quantity && (
              <p className="text-xs text-muted-foreground">متوفر: {quote.quantity}</p>
            )}
          </div>
        </div>

        {/* Rental Options */}
        <div className="p-3 space-y-2">
          {quote.options.map((option, idx) => (
            <RentalOptionRow
              key={idx}
              option={option}
              onPurchase={handlePurchase}
              isPurchasing={isPurchasing}
              disabled={disabled}
            />
          ))}
        </div>
      </div>
    );
  }

  // Temp/Voice mode - single quote
  return (
    <div className="bg-card rounded-xl border border-border p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <span className="text-primary font-bold">{quote.provider.charAt(0)}</span>
          </div>
          <div>
            <p className="font-medium">{quote.provider}</p>
            {quote.quantity && (
              <p className="text-xs text-muted-foreground">متوفر: {quote.quantity}</p>
            )}
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-primary">{quote.price_label}</span>
          <Button
            size="sm"
            onClick={() => handlePurchase(quote.quote_token)}
            loading={isPurchasing}
            disabled={disabled}
          >
            شراء
          </Button>
        </div>
      </div>
    </div>
  );
}

interface RentalOptionRowProps {
  option: RentalOption;
  onPurchase: (quoteToken: string) => void;
  isPurchasing: boolean;
  disabled: boolean;
}

function RentalOptionRow({ option, onPurchase, isPurchasing, disabled }: RentalOptionRowProps) {
  return (
    <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
      <div>
        <p className="font-medium">{option.duration_label}</p>
        {option.can_renew && (
          <p className="text-xs text-success">قابل للتجديد</p>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="font-bold text-primary">{option.price_label}</span>
        <Button
          size="sm"
          onClick={() => onPurchase(option.quote_token)}
          loading={isPurchasing}
          disabled={disabled}
        >
          شراء
        </Button>
      </div>
    </div>
  );
}

// Mode Tabs
interface ModeTabsProps {
  modes: { key: string; label: string }[];
  selectedMode: string;
  onSelect: (mode: string) => void;
}

export function ModeTabs({ modes, selectedMode, onSelect }: ModeTabsProps) {
  return (
    <div className="flex bg-muted p-1 rounded-xl gap-1">
      {modes.map((mode) => (
        <button
          key={mode.key}
          onClick={() => {
            if (mode.key !== selectedMode) {
              haptic('selection');
              onSelect(mode.key);
            }
          }}
          className={clsx(
            'flex-1 px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200',
            selectedMode === mode.key
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          {mode.label}
        </button>
      ))}
    </div>
  );
}
