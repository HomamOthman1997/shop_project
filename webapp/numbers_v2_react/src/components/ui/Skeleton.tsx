import { clsx } from 'clsx';

interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string | number;
  height?: string | number;
}

export function Skeleton({ 
  className, 
  variant = 'rectangular',
  width,
  height,
}: SkeletonProps) {
  return (
    <div
      className={clsx(
        'skeleton',
        variant === 'circular' && 'rounded-full',
        variant === 'text' && 'rounded-md',
        variant === 'rectangular' && 'rounded-lg',
        className
      )}
      style={{ width, height }}
    />
  );
}

// Pre-built skeleton patterns
export function ServiceCardSkeleton() {
  return (
    <div className="flex items-center gap-3 p-4 bg-card rounded-xl">
      <Skeleton variant="circular" className="w-10 h-10" />
      <div className="flex-1 space-y-2">
        <Skeleton variant="text" className="h-4 w-24" />
        <Skeleton variant="text" className="h-3 w-16" />
      </div>
      <Skeleton variant="text" className="h-5 w-12" />
    </div>
  );
}

export function OrderCardSkeleton() {
  return (
    <div className="p-4 bg-card rounded-xl space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Skeleton variant="circular" className="w-10 h-10" />
          <div className="space-y-2">
            <Skeleton variant="text" className="h-4 w-28" />
            <Skeleton variant="text" className="h-3 w-20" />
          </div>
        </div>
        <Skeleton variant="text" className="h-6 w-16 rounded-full" />
      </div>
      <div className="flex items-center justify-between pt-2 border-t border-border">
        <Skeleton variant="text" className="h-5 w-32" />
        <Skeleton variant="text" className="h-8 w-20 rounded-lg" />
      </div>
    </div>
  );
}

export function QuoteCardSkeleton() {
  return (
    <div className="flex items-center justify-between p-4 bg-card rounded-xl">
      <div className="flex items-center gap-3">
        <Skeleton variant="circular" className="w-8 h-8" />
        <div className="space-y-2">
          <Skeleton variant="text" className="h-4 w-20" />
          <Skeleton variant="text" className="h-3 w-14" />
        </div>
      </div>
      <Skeleton variant="rectangular" className="h-9 w-20 rounded-lg" />
    </div>
  );
}

export function AccountSkeleton() {
  return (
    <div className="space-y-4">
      <div className="p-6 bg-card rounded-xl space-y-4">
        <div className="flex items-center gap-4">
          <Skeleton variant="circular" className="w-16 h-16" />
          <div className="space-y-2">
            <Skeleton variant="text" className="h-5 w-32" />
            <Skeleton variant="text" className="h-4 w-24" />
          </div>
        </div>
        <div className="pt-4 border-t border-border">
          <Skeleton variant="text" className="h-8 w-28 mx-auto" />
        </div>
      </div>
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex items-center justify-between p-3 bg-card rounded-lg">
            <Skeleton variant="text" className="h-4 w-32" />
            <Skeleton variant="text" className="h-4 w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <ServiceCardSkeleton key={i} />
      ))}
    </div>
  );
}
