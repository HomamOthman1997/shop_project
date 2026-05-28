import { clsx } from 'clsx';
import { Loader2 } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: ReactNode;
  children: ReactNode;
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  children,
  className,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={clsx(
        'inline-flex items-center justify-center gap-2 font-medium transition-all duration-200',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        'active:scale-[0.98]',
        // Variants
        variant === 'primary' && 'bg-primary text-primary-foreground hover:bg-primary/90',
        variant === 'secondary' && 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        variant === 'ghost' && 'bg-transparent text-foreground hover:bg-muted',
        variant === 'danger' && 'bg-danger text-danger-foreground hover:bg-danger/90',
        variant === 'success' && 'bg-success text-success-foreground hover:bg-success/90',
        // Sizes
        size === 'sm' && 'px-3 py-1.5 text-sm rounded-lg',
        size === 'md' && 'px-4 py-2 text-sm rounded-xl',
        size === 'lg' && 'px-6 py-3 text-base rounded-xl',
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : icon ? (
        icon
      ) : null}
      {children}
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  children: ReactNode;
}

export function IconButton({
  variant = 'ghost',
  size = 'md',
  loading = false,
  children,
  className,
  disabled,
  ...props
}: IconButtonProps) {
  return (
    <button
      className={clsx(
        'inline-flex items-center justify-center transition-all duration-200',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        'active:scale-[0.95]',
        // Variants
        variant === 'primary' && 'bg-primary text-primary-foreground hover:bg-primary/90',
        variant === 'secondary' && 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        variant === 'ghost' && 'text-muted-foreground hover:text-foreground hover:bg-muted',
        variant === 'danger' && 'text-danger hover:bg-danger/10',
        // Sizes
        size === 'sm' && 'w-8 h-8 rounded-lg',
        size === 'md' && 'w-10 h-10 rounded-xl',
        size === 'lg' && 'w-12 h-12 rounded-xl',
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : children}
    </button>
  );
}
