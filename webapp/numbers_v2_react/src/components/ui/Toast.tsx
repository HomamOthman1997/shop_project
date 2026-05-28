import { clsx } from 'clsx';
import { useEffect, useState } from 'react';
import { CheckCircle, XCircle, AlertCircle, Info, X } from 'lucide-react';

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

let toastId = 0;
const listeners: Set<(toast: Toast) => void> = new Set();

export function toast(type: ToastType, message: string, duration = 4000) {
  const id = String(++toastId);
  const newToast: Toast = { id, type, message, duration };
  listeners.forEach((listener) => listener(newToast));
  return id;
}

toast.success = (message: string, duration?: number) => toast('success', message, duration);
toast.error = (message: string, duration?: number) => toast('error', message, duration);
toast.warning = (message: string, duration?: number) => toast('warning', message, duration);
toast.info = (message: string, duration?: number) => toast('info', message, duration);

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const handleToast = (newToast: Toast) => {
      setToasts((prev) => [...prev, newToast]);
      
      if (newToast.duration && newToast.duration > 0) {
        setTimeout(() => {
          setToasts((prev) => prev.filter((t) => t.id !== newToast.id));
        }, newToast.duration);
      }
    };

    listeners.add(handleToast);
    return () => {
      listeners.delete(handleToast);
    };
  }, []);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const icons: Record<ToastType, React.ReactNode> = {
    success: <CheckCircle className="w-5 h-5" />,
    error: <XCircle className="w-5 h-5" />,
    warning: <AlertCircle className="w-5 h-5" />,
    info: <Info className="w-5 h-5" />,
  };

  return (
    <div className="fixed top-4 left-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={clsx(
            'flex items-center gap-3 p-4 rounded-xl shadow-lg pointer-events-auto',
            'animate-[slide-up_0.3s_ease-out]',
            t.type === 'success' && 'bg-success/10 text-success border border-success/20',
            t.type === 'error' && 'bg-danger/10 text-danger border border-danger/20',
            t.type === 'warning' && 'bg-warning/10 text-warning border border-warning/20',
            t.type === 'info' && 'bg-primary/10 text-primary border border-primary/20'
          )}
        >
          {icons[t.type]}
          <span className="flex-1 text-sm font-medium">{t.message}</span>
          <button
            onClick={() => removeToast(t.id)}
            className="p-1 rounded-lg hover:bg-white/10 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
