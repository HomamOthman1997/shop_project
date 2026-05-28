import { useCallback } from 'react';
import { RefreshCw, ClipboardList } from 'lucide-react';
import useSWR from 'swr';
import { clsx } from 'clsx';
import { useOrdersStore } from '@/stores';
import { Header, ScreenContainer } from '@/components/layout';
import { IconButton, SegmentedControl, EmptyState, toast } from '@/components/ui';
import { OrderCardSkeleton } from '@/components/ui/Skeleton';
import { OrderCard } from './OrderCard';
import {
  fetchOrders,
  refreshOrder,
  resendCode,
  replaceOrder,
  alternateProvider,
  fetchRentalSms,
  finishRental,
  renewRental,
  wakeRental,
  haptic,
} from '@/api/client';
import type { OrderAction } from '@/types';

const modeOptions = [
  { value: 'all', label: 'الكل' },
  { value: 'temp', label: 'مؤقت' },
  { value: 'rental', label: 'إيجار' },
  { value: 'voice', label: 'صوتي' },
];

export function OrdersScreen() {
  const { filterMode, setFilterMode, refreshingOrderId, setRefreshingOrderId } = useOrdersStore();
  
  // Fetch orders
  const {
    data: orders,
    isLoading,
    mutate: refreshOrders,
  } = useSWR(
    ['orders', filterMode],
    () => fetchOrders(filterMode),
    { 
      revalidateOnFocus: true,
      refreshInterval: 30000, // Auto-refresh every 30 seconds
    }
  );

  // Refresh all orders
  const handleRefreshAll = () => {
    haptic('light');
    refreshOrders();
  };

  // Refresh single order
  const handleRefreshOrder = useCallback(async (orderId: string) => {
    setRefreshingOrderId(orderId);
    try {
      const updatedOrder = await refreshOrder(orderId);
      // Update the order in the list
      refreshOrders((current) => {
        if (!current) return current;
        return current.map((o) => (o.id === orderId ? updatedOrder : o));
      }, false);
      
      if (updatedOrder.code) {
        haptic('success');
        toast.success('تم استلام الكود!');
      }
    } catch (error) {
      haptic('error');
      const message = error instanceof Error ? error.message : 'فشل التحديث';
      toast.error(message);
    } finally {
      setRefreshingOrderId(null);
    }
  }, [refreshOrders, setRefreshingOrderId]);

  // Handle order actions
  const handleOrderAction = useCallback(async (
    orderId: string,
    action: string,
    _actionData?: OrderAction
  ) => {
    switch (action) {
      case 'second_code':
        await resendCode(orderId);
        toast.success('تم طلب كود جديد');
        break;
      case 'replace':
        await replaceOrder(orderId);
        toast.success('تم الاستبدال');
        break;
      case 'alternate_provider':
        await alternateProvider(orderId);
        toast.success('تم التبديل لمزود آخر');
        break;
      case 'rental_sms':
        const smsResult = await fetchRentalSms(orderId);
        if (smsResult.messages.length > 0) {
          toast.success(`${smsResult.messages.length} رسالة`);
        } else {
          toast.info('لا توجد رسائل جديدة');
        }
        break;
      case 'rental_finish':
        await finishRental(orderId);
        toast.success('تم إنهاء الإيجار');
        break;
      case 'rental_renew':
        await renewRental(orderId);
        toast.success('تم التجديد');
        break;
      case 'rental_wake':
        await wakeRental(orderId);
        toast.success('تم التنشيط');
        break;
      default:
        console.warn('Unknown action:', action);
        return;
    }

    // Refresh orders list
    refreshOrders();
  }, [refreshOrders]);

  return (
    <ScreenContainer
      header={
        <Header
          title="طلباتي"
          action={
            <IconButton onClick={handleRefreshAll} disabled={isLoading}>
              <RefreshCw className={clsx('w-5 h-5', isLoading && 'animate-spin')} />
            </IconButton>
          }
        />
      }
    >
      <div className="space-y-4">
        {/* Filter */}
        <SegmentedControl
          options={modeOptions}
          value={filterMode}
          onChange={setFilterMode}
        />

        {/* Orders List */}
        {isLoading ? (
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <OrderCardSkeleton key={i} />
            ))}
          </div>
        ) : !orders || orders.length === 0 ? (
          <EmptyState
            icon={<ClipboardList className="w-8 h-8" />}
            title="لا توجد طلبات"
            description="اشترِ رقمًا جديدًا لبدء استقبال الرسائل"
          />
        ) : (
          <div className="space-y-4">
            {orders.map((order) => (
              <OrderCard
                key={order.id}
                order={order}
                onRefresh={handleRefreshOrder}
                onAction={handleOrderAction}
                isRefreshing={refreshingOrderId === order.id}
              />
            ))}
          </div>
        )}
      </div>
    </ScreenContainer>
  );
}
