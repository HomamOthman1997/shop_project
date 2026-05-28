import { User, Wallet, Clock, Globe, ChevronLeft } from 'lucide-react';
import useSWR from 'swr';
import { clsx } from 'clsx';
import { useState } from 'react';
import { useAppStore } from '@/stores';
import { Header, ScreenContainer } from '@/components/layout';
import { Card, Badge, toast } from '@/components/ui';
import { AccountSkeleton } from '@/components/ui/Skeleton';
import { fetchAccount, updateLanguage, haptic } from '@/api/client';
import type { WalletActivity } from '@/types';

const languages = [
  { code: 'ar', name: 'العربية', flag: '🇸🇦' },
  { code: 'en', name: 'English', flag: '🇺🇸' },
];

export function AccountScreen() {
  const { language, setLanguage } = useAppStore();
  const [showLanguageSelector, setShowLanguageSelector] = useState(false);

  // Fetch account data
  const { data: account, isLoading } = useSWR('account', fetchAccount, {
    revalidateOnFocus: true,
  });

  // Handle language change
  const handleLanguageChange = async (langCode: string) => {
    try {
      await updateLanguage(langCode);
      setLanguage(langCode);
      haptic('success');
      toast.success('تم تغيير اللغة');
      setShowLanguageSelector(false);
    } catch (error) {
      haptic('error');
      toast.error('فشل تغيير اللغة');
    }
  };

  // Get activity icon and color
  const getActivityStyle = (activity: WalletActivity) => {
    const isCredit = activity.direction === 'credit';
    return {
      color: isCredit ? 'text-success' : 'text-foreground',
      sign: isCredit ? '+' : '',
    };
  };

  if (isLoading) {
    return (
      <ScreenContainer header={<Header title="حسابي" />}>
        <AccountSkeleton />
      </ScreenContainer>
    );
  }

  return (
    <>
      <ScreenContainer header={<Header title="حسابي" />}>
        <div className="space-y-4">
          {/* User Card */}
          <Card className="p-6">
            <div className="flex items-center gap-4 mb-6">
              <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center">
                <User className="w-8 h-8 text-primary" />
              </div>
              <div>
                <p className="text-lg font-semibold">
                  {account?.user.username || `مستخدم ${account?.user.id}`}
                </p>
                <p className="text-sm text-muted-foreground">
                  عضو منذ {account?.user.joined_at ? new Date(account.user.joined_at).toLocaleDateString('ar') : '-'}
                </p>
              </div>
            </div>

            {/* Balance */}
            <div className="bg-gradient-to-br from-primary/20 to-primary/5 rounded-xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground mb-1">
                <Wallet className="w-4 h-4" />
                <span className="text-sm">الرصيد</span>
              </div>
              <p className="text-3xl font-bold text-foreground">
                {account?.wallet.balance_label || '$0.00'}
              </p>
            </div>
          </Card>

          {/* Settings */}
          <Card>
            <button
              onClick={() => setShowLanguageSelector(true)}
              className="w-full flex items-center justify-between p-4 hover:bg-muted transition-colors"
            >
              <div className="flex items-center gap-3">
                <Globe className="w-5 h-5 text-muted-foreground" />
                <span>اللغة</span>
              </div>
              <div className="flex items-center gap-2 text-muted-foreground">
                <span>{languages.find((l) => l.code === language)?.name || 'العربية'}</span>
                <ChevronLeft className="w-4 h-4" />
              </div>
            </button>
          </Card>

          {/* Recent Activity */}
          {account?.recent_activity && account.recent_activity.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-2">
                <Clock className="w-4 h-4" />
                النشاط الأخير
              </h3>
              <Card>
                <div className="divide-y divide-border">
                  {account.recent_activity.slice(0, 10).map((activity) => {
                    const style = getActivityStyle(activity);
                    return (
                      <div
                        key={activity.id}
                        className="flex items-center justify-between p-4"
                      >
                        <div>
                          <p className="font-medium text-sm">{activity.label}</p>
                          <p className="text-xs text-muted-foreground">
                            {new Date(activity.created_at).toLocaleString('ar')}
                          </p>
                        </div>
                        <span className={clsx('font-mono font-medium', style.color)}>
                          {style.sign}{activity.amount_label}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </Card>
            </div>
          )}
        </div>
      </ScreenContainer>

      {/* Language Selector Modal */}
      {showLanguageSelector && (
        <div className="fixed inset-0 z-50 bg-background">
          <header className="flex items-center gap-3 px-4 py-3 border-b border-border">
            <button
              onClick={() => setShowLanguageSelector(false)}
              className="p-2 -mr-2 hover:bg-muted rounded-lg"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
            <h2 className="text-lg font-semibold">اختر اللغة</h2>
          </header>
          <div className="p-4 space-y-2">
            {languages.map((lang) => (
              <button
                key={lang.code}
                onClick={() => handleLanguageChange(lang.code)}
                className={clsx(
                  'w-full flex items-center gap-3 p-4 rounded-xl transition-colors',
                  language === lang.code ? 'bg-primary/10 text-primary' : 'bg-card hover:bg-muted'
                )}
              >
                <span className="text-2xl">{lang.flag}</span>
                <span className="font-medium">{lang.name}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
