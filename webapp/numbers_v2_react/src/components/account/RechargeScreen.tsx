import { Copy, Wallet, CreditCard, ExternalLink } from 'lucide-react';
import useSWR from 'swr';
import { Header, ScreenContainer } from '@/components/layout';
import { Card, Badge, toast } from '@/components/ui';
import { AccountSkeleton } from '@/components/ui/Skeleton';
import { fetchRecharge, haptic } from '@/api/client';
import type { PaymentMethod } from '@/types';

export function RechargeScreen() {
  // Fetch recharge data
  const { data: rechargeData, isLoading } = useSWR('recharge', fetchRecharge, {
    revalidateOnFocus: true,
  });

  // Copy to clipboard
  const copyToClipboard = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      haptic('success');
      toast.success(`تم نسخ ${label}`);
    } catch {
      haptic('error');
      toast.error('فشل النسخ');
    }
  };

  if (isLoading) {
    return (
      <ScreenContainer header={<Header title="شحن الرصيد" />}>
        <AccountSkeleton />
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer header={<Header title="شحن الرصيد" />}>
      <div className="space-y-4">
        {/* Balance Card */}
        <Card className="p-6">
          <div className="bg-gradient-to-br from-primary/20 to-primary/5 rounded-xl p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <Wallet className="w-4 h-4" />
              <span className="text-sm">رصيدك الحالي</span>
            </div>
            <p className="text-3xl font-bold text-foreground">
              {rechargeData?.wallet.balance_label || '$0.00'}
            </p>
          </div>
        </Card>

        {/* Payment Methods */}
        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-2">
            <CreditCard className="w-4 h-4" />
            طرق الدفع
          </h3>

          <div className="space-y-3">
            {rechargeData?.methods.map((method) => (
              <PaymentMethodCard
                key={method.code}
                method={method}
                onCopy={copyToClipboard}
              />
            ))}
          </div>
        </div>

        {/* Notice */}
        <Card className="p-4 bg-warning/5 border-warning/20">
          <p className="text-sm text-warning">
            بعد إرسال الدفعة، أرسل إثبات الدفع للدعم لشحن رصيدك.
          </p>
        </Card>
      </div>
    </ScreenContainer>
  );
}

interface PaymentMethodCardProps {
  method: PaymentMethod;
  onCopy: (text: string, label: string) => void;
}

function PaymentMethodCard({ method, onCopy }: PaymentMethodCardProps) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg font-semibold">{method.title}</span>
          <Badge variant="muted">{method.currency}</Badge>
        </div>
        <span className="text-sm text-muted-foreground">{method.rate_label}</span>
      </div>

      {/* Target Address */}
      <div className="bg-muted rounded-lg p-3 mb-3">
        <div className="flex items-center justify-between">
          <p className="font-mono text-sm break-all" dir="ltr">
            {method.target}
          </p>
          <button
            onClick={() => onCopy(method.target, 'العنوان')}
            className="p-2 hover:bg-card rounded-lg transition-colors flex-shrink-0 mr-2"
          >
            <Copy className="w-4 h-4 text-muted-foreground" />
          </button>
        </div>
      </div>

      {/* Instructions */}
      {method.instructions && (
        <p className="text-sm text-muted-foreground mb-3">{method.instructions}</p>
      )}

      {/* Support */}
      {method.support && (
        <a
          href={`https://t.me/${method.support.replace('@', '')}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 text-sm text-primary hover:underline"
        >
          <ExternalLink className="w-4 h-4" />
          تواصل مع الدعم: {method.support}
        </a>
      )}
    </Card>
  );
}
