import { HelpCircle, MessageCircle, ExternalLink, ChevronLeft } from 'lucide-react';
import useSWR from 'swr';
import { Header, ScreenContainer } from '@/components/layout';
import { Card, EmptyState } from '@/components/ui';
import { ListSkeleton } from '@/components/ui/Skeleton';
import { fetchSupport, haptic } from '@/api/client';
import type { SupportCategory } from '@/types';

export function SupportScreen() {
  // Fetch support data
  const { data: supportData, isLoading } = useSWR('support', fetchSupport, {
    revalidateOnFocus: false,
  });

  // Handle category click - opens Telegram support
  const handleCategoryClick = (category: SupportCategory) => {
    haptic('selection');
    // For now, open Telegram support - in the future this could open a ticket form
    window.open('https://t.me/phantom_support', '_blank');
  };

  if (isLoading) {
    return (
      <ScreenContainer header={<Header title="الدعم" />}>
        <ListSkeleton count={3} />
      </ScreenContainer>
    );
  }

  const categories = supportData?.categories || [];

  return (
    <ScreenContainer header={<Header title="الدعم" />}>
      <div className="space-y-4">
        {/* Info Card */}
        <Card className="p-4 bg-primary/5 border-primary/20">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
              <MessageCircle className="w-5 h-5 text-primary" />
            </div>
            <div>
              <p className="font-medium mb-1">هل تحتاج مساعدة؟</p>
              <p className="text-sm text-muted-foreground">
                اختر موضوع الدعم أدناه أو تواصل معنا مباشرة عبر تيليغرام.
              </p>
            </div>
          </div>
        </Card>

        {/* Categories */}
        {categories.length === 0 ? (
          <EmptyState
            icon={<HelpCircle className="w-8 h-8" />}
            title="لا توجد فئات دعم"
            description="يرجى التواصل مع الدعم مباشرة"
          />
        ) : (
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-muted-foreground">موضوعات الدعم</h3>
            <Card>
              <div className="divide-y divide-border">
                {categories.map((category) => (
                  <button
                    key={category.key}
                    onClick={() => handleCategoryClick(category)}
                    className="w-full flex items-center justify-between p-4 hover:bg-muted transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center">
                        {getCategoryIcon(category.key)}
                      </div>
                      <span className="font-medium">{category.label}</span>
                    </div>
                    <ChevronLeft className="w-5 h-5 text-muted-foreground" />
                  </button>
                ))}
              </div>
            </Card>
          </div>
        )}

        {/* Direct Support Link */}
        <Card className="p-4">
          <a
            href="https://t.me/phantom_support"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-between"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                <MessageCircle className="w-5 h-5 text-primary" />
              </div>
              <div>
                <p className="font-medium">تواصل مباشر</p>
                <p className="text-sm text-muted-foreground">@phantom_support</p>
              </div>
            </div>
            <ExternalLink className="w-5 h-5 text-muted-foreground" />
          </a>
        </Card>

        {/* FAQ Section */}
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-muted-foreground">أسئلة شائعة</h3>
          <Card>
            <div className="divide-y divide-border">
              <FAQItem
                question="كيف أشحن رصيدي؟"
                answer="اذهب إلى قسم شحن الرصيد، اختر طريقة الدفع، وأرسل إثبات الدفع للدعم."
              />
              <FAQItem
                question="ماذا أفعل إذا لم أستلم الكود؟"
                answer="اضغط على زر التحديث في الطلب. إذا لم يصل الكود خلال دقيقتين، سيتم استرداد المبلغ تلقائياً."
              />
              <FAQItem
                question="هل يمكنني استرداد المبلغ؟"
                answer="نعم، إذا لم يتم استلام الكود، يتم الاسترداد تلقائياً. للحالات الأخرى، تواصل مع الدعم."
              />
            </div>
          </Card>
        </div>
      </div>
    </ScreenContainer>
  );
}

// Helper to get category icon
function getCategoryIcon(key: string) {
  switch (key) {
    case 'numbers':
      return <MessageCircle className="w-5 h-5 text-muted-foreground" />;
    case 'user_balance':
      return <HelpCircle className="w-5 h-5 text-muted-foreground" />;
    default:
      return <HelpCircle className="w-5 h-5 text-muted-foreground" />;
  }
}

// FAQ Item component
interface FAQItemProps {
  question: string;
  answer: string;
}

function FAQItem({ question, answer }: FAQItemProps) {
  return (
    <div className="p-4">
      <p className="font-medium mb-1">{question}</p>
      <p className="text-sm text-muted-foreground">{answer}</p>
    </div>
  );
}
