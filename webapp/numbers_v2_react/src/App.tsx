import { useEffect } from 'react';
import useSWR from 'swr';
import { useAppStore } from '@/stores';
import { BottomNavigation } from '@/components/layout';
import { ToastContainer } from '@/components/ui';
import { PurchaseScreen } from '@/components/purchase';
import { OrdersScreen } from '@/components/orders';
import { AccountScreen, RechargeScreen } from '@/components/account';
import { SupportScreen } from '@/components/support';
import { fetchBootstrap } from '@/api/client';
import { Loader2 } from 'lucide-react';

function LoadingScreen() {
  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-4">
      <Loader2 className="w-10 h-10 text-primary animate-spin" />
      <p className="text-muted-foreground">جاري التحميل...</p>
    </div>
  );
}

function ErrorScreen({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-4 p-4">
      <div className="w-16 h-16 rounded-full bg-danger/10 flex items-center justify-center">
        <span className="text-3xl text-danger">!</span>
      </div>
      <p className="text-lg font-medium">حدث خطأ</p>
      <p className="text-muted-foreground text-center">{message}</p>
      <button
        onClick={onRetry}
        className="px-6 py-2 bg-primary text-primary-foreground rounded-xl font-medium"
      >
        إعادة المحاولة
      </button>
    </div>
  );
}

export default function App() {
  const { screen, isInitializing, setIsInitializing, setBootstrap, globalError, setGlobalError } = useAppStore();

  // Fetch bootstrap data
  const { data: bootstrap, error: bootstrapError, mutate } = useSWR(
    'bootstrap',
    fetchBootstrap,
    {
      revalidateOnFocus: false,
      onSuccess: (data) => {
        setBootstrap(data);
        setIsInitializing(false);
      },
      onError: (err) => {
        setGlobalError(err.message || 'فشل تحميل البيانات');
        setIsInitializing(false);
      },
    }
  );

  // Initialize Telegram WebApp
  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (tg) {
      tg.ready();
      tg.expand();
    }
  }, []);

  // Show loading
  if (isInitializing && !bootstrap) {
    return <LoadingScreen />;
  }

  // Show error
  if (bootstrapError || globalError) {
    return (
      <ErrorScreen
        message={globalError || bootstrapError?.message || 'فشل تحميل البيانات'}
        onRetry={() => {
          setGlobalError(null);
          setIsInitializing(true);
          mutate();
        }}
      />
    );
  }

  // Render current screen
  const renderScreen = () => {
    switch (screen) {
      case 'purchase':
        return <PurchaseScreen />;
      case 'orders':
        return <OrdersScreen />;
      case 'account':
        return <AccountScreen />;
      case 'recharge':
        return <RechargeScreen />;
      case 'support':
        return <SupportScreen />;
      default:
        return <PurchaseScreen />;
    }
  };

  return (
    <div className="min-h-screen bg-background">
      {renderScreen()}
      <BottomNavigation />
      <ToastContainer />
    </div>
  );
}
