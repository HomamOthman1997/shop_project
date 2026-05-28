import {
  Copy,
  RefreshCw,
  RotateCcw,
  ArrowRightLeft,
  MessageSquare,
  Power,
  Clock,
  CheckCircle,
  AlertCircle,
  Phone,
  Download,
  StickyNote,
} from 'lucide-react';
import { useState } from 'react';
import { Button, IconButton, Badge, toast } from '@/components/ui';
import { haptic } from '@/api/client';
import type { Order, OrderAction } from '@/types';

interface OrderCardProps {
  order: Order;
  onRefresh: (orderId: string) => Promise<void>;
  onAction: (orderId: string, action: string, actionData?: OrderAction) => Promise<void>;
  isRefreshing: boolean;
}

export function OrderCard({ order, onRefresh, onAction, isRefreshing }: OrderCardProps) {
  const [actionLoading, setActionLoading] = useState<string | null>(null);

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

  // Handle action
  const handleAction = async (actionKey: string, actionData?: OrderAction) => {
    if (actionData?.method === 'CLIENT') {
      // Client-side actions (copy)
      if (actionKey === 'copy_number') {
        copyToClipboard(order.number, 'الرقم');
      } else if (actionKey === 'copy_code' && order.code) {
        copyToClipboard(order.code, 'الكود');
      }
      return;
    }

    setActionLoading(actionKey);
    try {
      await onAction(order.id, actionKey, actionData);
      haptic('success');
    } catch (error) {
      haptic('error');
      const message = error instanceof Error ? error.message : 'فشل الإجراء';
      toast.error(message);
    } finally {
      setActionLoading(null);
    }
  };

  // Status badge
  const getStatusBadge = () => {
    const { tone } = order.customer_state;
    const variants: Record<string, 'success' | 'warning' | 'danger' | 'muted' | 'default'> = {
      'success': 'success',
      'waiting': 'warning',
      'pending-refund': 'warning',
      'refunded': 'muted',
      'danger': 'danger',
    };
    
    const labels: Record<string, string> = {
      'awaiting_provider_webhook': 'بانتظار الكود',
      'code_received': 'تم الاستلام',
      'refund_pending': 'قيد الاسترداد',
      'refunded': 'مسترد',
      'support_review_pending': 'قيد المراجعة',
      'waiting_for_recording': 'بانتظار المكالمة',
      'call_received': 'تم الاستلام',
    };

    return (
      <Badge variant={variants[tone] || 'default'}>
        {labels[order.customer_state.key] || order.public_status}
      </Badge>
    );
  };

  // Mode icon
  const getModeIcon = () => {
    switch (order.mode) {
      case 'voice':
        return <Phone className="w-4 h-4" />;
      case 'rental':
        return <Clock className="w-4 h-4" />;
      default:
        return <MessageSquare className="w-4 h-4" />;
    }
  };

  // Available actions
  const actions = order.actions || {};

  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
              {getModeIcon()}
            </div>
            <div>
              <p className="font-medium">{order.service_name}</p>
              <p className="text-xs text-muted-foreground">{order.country_name}</p>
            </div>
          </div>
          {getStatusBadge()}
        </div>

        {/* Number */}
        <div className="flex items-center justify-between bg-muted rounded-lg p-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-lg font-bold" dir="ltr">
              {order.number_formatted || order.number}
            </span>
          </div>
          <IconButton
            size="sm"
            onClick={() => copyToClipboard(order.number, 'الرقم')}
          >
            <Copy className="w-4 h-4" />
          </IconButton>
        </div>

        {/* Code (if received) */}
        {order.code && (
          <div className="mt-2 flex items-center justify-between bg-success/10 rounded-lg p-3">
            <div className="flex items-center gap-2">
              <CheckCircle className="w-5 h-5 text-success" />
              <span className="font-mono text-xl font-bold text-success">{order.code}</span>
            </div>
            <IconButton
              size="sm"
              onClick={() => copyToClipboard(order.code!, 'الكود')}
            >
              <Copy className="w-4 h-4" />
            </IconButton>
          </div>
        )}

        {/* Full SMS (if available) */}
        {order.full_sms && (
          <div className="mt-2 p-3 bg-muted rounded-lg">
            <p className="text-xs text-muted-foreground mb-1">الرسالة الكاملة</p>
            <p className="text-sm" dir="ltr">{order.full_sms}</p>
          </div>
        )}

        {/* Rental info */}
        {order.mode === 'rental' && (
          <div className="mt-2 flex items-center gap-4 text-sm text-muted-foreground">
            {order.duration_label && (
              <span className="flex items-center gap-1">
                <Clock className="w-4 h-4" />
                {order.duration_label}
              </span>
            )}
            {order.end_date && (
              <span>ينتهي: {new Date(order.end_date).toLocaleDateString('ar')}</span>
            )}
          </div>
        )}

        {/* Voice info */}
        {order.mode === 'voice' && (
          <div className="mt-2 flex items-center gap-4 text-sm text-muted-foreground">
            {order.calls_count !== undefined && (
              <span className="flex items-center gap-1">
                <Phone className="w-4 h-4" />
                {order.calls_count} مكالمة
              </span>
            )}
            {order.recording_available && (
              <span className="flex items-center gap-1 text-success">
                <CheckCircle className="w-4 h-4" />
                تسجيل متاح
              </span>
            )}
          </div>
        )}

        {/* Refund info */}
        {order.refund && (
          <div className="mt-2 p-3 bg-warning/10 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-warning" />
            <div>
              <p className="text-sm font-medium">
                {order.refund.status === 'refund_pending' ? 'قيد الاسترداد' : 'مسترد'}
              </p>
              {order.refund.amount_label && (
                <p className="text-xs text-muted-foreground">{order.refund.amount_label}</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="p-3 flex flex-wrap gap-2">
        {/* Refresh */}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onRefresh(order.id)}
          loading={isRefreshing}
          icon={<RefreshCw className="w-4 h-4" />}
        >
          تحديث
        </Button>

        {/* Second Code / Resend */}
        {actions.second_code?.enabled && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => handleAction('second_code', actions.second_code)}
            loading={actionLoading === 'second_code'}
            icon={<RotateCcw className="w-4 h-4" />}
          >
            كود ثاني
          </Button>
        )}

        {/* Replace */}
        {actions.replace?.enabled && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => handleAction('replace', actions.replace)}
            loading={actionLoading === 'replace'}
            icon={<RotateCcw className="w-4 h-4" />}
          >
            استبدال
          </Button>
        )}

        {/* Alternate Provider */}
        {actions.alternate_provider?.enabled && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => handleAction('alternate_provider', actions.alternate_provider)}
            loading={actionLoading === 'alternate_provider'}
            icon={<ArrowRightLeft className="w-4 h-4" />}
          >
            مزود آخر
          </Button>
        )}

        {/* Rental Actions */}
        {order.mode === 'rental' && (
          <>
            {actions.rental_sms?.enabled && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => handleAction('rental_sms', actions.rental_sms)}
                loading={actionLoading === 'rental_sms'}
                icon={<MessageSquare className="w-4 h-4" />}
              >
                الرسائل
              </Button>
            )}
            {actions.rental_renew?.enabled && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => handleAction('rental_renew', actions.rental_renew)}
                loading={actionLoading === 'rental_renew'}
                icon={<RefreshCw className="w-4 h-4" />}
              >
                تجديد
              </Button>
            )}
            {actions.rental_wake?.enabled && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => handleAction('rental_wake', actions.rental_wake)}
                loading={actionLoading === 'rental_wake'}
                icon={<Power className="w-4 h-4" />}
              >
                تنشيط
              </Button>
            )}
            {actions.rental_notes?.enabled && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => handleAction('rental_notes', actions.rental_notes)}
                loading={actionLoading === 'rental_notes'}
                icon={<StickyNote className="w-4 h-4" />}
              >
                ملاحظات
              </Button>
            )}
            {actions.rental_finish?.enabled && (
              <Button
                size="sm"
                variant="danger"
                onClick={() => handleAction('rental_finish', actions.rental_finish)}
                loading={actionLoading === 'rental_finish'}
              >
                إنهاء
              </Button>
            )}
          </>
        )}

        {/* Voice Actions */}
        {order.mode === 'voice' && (
          <>
            {actions.download_recording?.enabled && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  if (order.recording_url) {
                    window.open(order.recording_url, '_blank');
                  }
                }}
                icon={<Download className="w-4 h-4" />}
              >
                تحميل التسجيل
              </Button>
            )}
          </>
        )}
      </div>

      {/* Timestamp */}
      <div className="px-4 pb-3">
        <p className="text-xs text-muted-foreground">
          {new Date(order.created_at).toLocaleString('ar')}
        </p>
      </div>
    </div>
  );
}
