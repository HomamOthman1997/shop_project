import { clsx } from 'clsx';
import { ShoppingCart, ClipboardList, User, Wallet, HelpCircle } from 'lucide-react';
import { useAppStore } from '@/stores';
import type { Screen } from '@/types';
import { haptic } from '@/api/client';

const tabs: { key: Screen; label: string; icon: React.ReactNode }[] = [
  { key: 'purchase', label: 'شراء', icon: <ShoppingCart className="w-5 h-5" /> },
  { key: 'orders', label: 'طلباتي', icon: <ClipboardList className="w-5 h-5" /> },
  { key: 'account', label: 'حسابي', icon: <User className="w-5 h-5" /> },
  { key: 'recharge', label: 'شحن', icon: <Wallet className="w-5 h-5" /> },
  { key: 'support', label: 'الدعم', icon: <HelpCircle className="w-5 h-5" /> },
];

export function BottomNavigation() {
  const { screen, setScreen } = useAppStore();

  const handleTabClick = (key: Screen) => {
    if (key !== screen) {
      haptic('selection');
      setScreen(key);
    }
  };

  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-card/95 backdrop-blur-lg border-t border-border safe-area-bottom">
      <div className="flex items-center justify-around h-16">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabClick(tab.key)}
            className={clsx(
              'flex flex-col items-center justify-center gap-1 flex-1 h-full transition-all duration-200',
              screen === tab.key
                ? 'text-primary'
                : 'text-muted-foreground hover:text-foreground'
            )}
          >
            <div className={clsx(
              'transition-transform duration-200',
              screen === tab.key && 'scale-110'
            )}>
              {tab.icon}
            </div>
            <span className="text-[10px] font-medium">{tab.label}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}

interface HeaderProps {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}

export function Header({ title, subtitle, action }: HeaderProps) {
  return (
    <header className="sticky top-0 z-40 bg-background/95 backdrop-blur-lg border-b border-border px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">{title}</h1>
          {subtitle && (
            <p className="text-xs text-muted-foreground">{subtitle}</p>
          )}
        </div>
        {action}
      </div>
    </header>
  );
}

interface ScreenContainerProps {
  children: React.ReactNode;
  header?: React.ReactNode;
  noPadding?: boolean;
}

export function ScreenContainer({ children, header, noPadding }: ScreenContainerProps) {
  return (
    <div className="min-h-screen pb-20 bg-background">
      {header}
      <main className={clsx(!noPadding && 'p-4')}>
        {children}
      </main>
    </div>
  );
}
