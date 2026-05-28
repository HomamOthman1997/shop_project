import { clsx } from 'clsx';
import type { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  interactive?: boolean;
}

export function Card({ children, className, onClick, interactive }: CardProps) {
  return (
    <div
      className={clsx(
        'bg-card rounded-xl border border-border',
        interactive && 'cursor-pointer transition-all duration-200 hover:bg-muted active:scale-[0.99]',
        className
      )}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </div>
  );
}

interface BadgeProps {
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'muted';
  children: ReactNode;
  className?: string;
}

export function Badge({ variant = 'default', children, className }: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full',
        variant === 'default' && 'bg-primary/10 text-primary',
        variant === 'success' && 'bg-success/10 text-success',
        variant === 'warning' && 'bg-warning/10 text-warning',
        variant === 'danger' && 'bg-danger/10 text-danger',
        variant === 'muted' && 'bg-muted text-muted-foreground',
        className
      )}
    >
      {children}
    </span>
  );
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
      {icon && (
        <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4 text-muted-foreground">
          {icon}
        </div>
      )}
      <h3 className="text-lg font-medium text-foreground mb-1">{title}</h3>
      {description && (
        <p className="text-sm text-muted-foreground mb-4 max-w-xs">{description}</p>
      )}
      {action}
    </div>
  );
}

interface SegmentedControlProps {
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

export function SegmentedControl({ options, value, onChange, className }: SegmentedControlProps) {
  return (
    <div className={clsx('flex bg-muted p-1 rounded-xl gap-1', className)}>
      {options.map((option) => (
        <button
          key={option.value}
          onClick={() => onChange(option.value)}
          className={clsx(
            'flex-1 px-3 py-2 text-sm font-medium rounded-lg transition-all duration-200',
            value === option.value
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

interface ModalProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  title?: string;
}

export function Modal({ open, onClose, children, title }: ModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center">
      <div 
        className="fixed inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-lg bg-card rounded-t-2xl sm:rounded-2xl p-6 animate-[slide-up_0.3s_ease-out] max-h-[85vh] overflow-y-auto">
        {title && (
          <h2 className="text-lg font-semibold mb-4">{title}</h2>
        )}
        {children}
      </div>
    </div>
  );
}

interface PullToRefreshProps {
  onRefresh: () => Promise<void>;
  children: ReactNode;
}

export function PullToRefresh({ onRefresh, children }: PullToRefreshProps) {
  // Simple wrapper - actual pull-to-refresh can be enhanced later
  return (
    <div className="min-h-full" onTouchEnd={() => {
      // Could implement actual pull detection here
    }}>
      {children}
    </div>
  );
}
