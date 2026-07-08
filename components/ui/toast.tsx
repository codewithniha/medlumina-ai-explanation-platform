'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from 'react'
import { CheckCircle2, X } from 'lucide-react'
import { cn } from '@/lib/utils'

type Toast = { id: number; title: string; description?: string }

type ToastContextValue = {
  toast: (t: { title: string; description?: string }) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback(
    ({ title, description }: { title: string; description?: string }) => {
      const id = Date.now() + Math.random()
      setToasts((prev) => [...prev, { id, title, description }])
      setTimeout(() => remove(id), 4000)
    },
    [remove],
  )

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4 sm:bottom-6 sm:right-6 sm:left-auto sm:items-end">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              'pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-2xl border border-border bg-card p-4 shadow-lg',
              'animate-in slide-in-from-bottom-4 fade-in',
            )}
            role="status"
          >
            <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-card-foreground">
                {t.title}
              </p>
              {t.description && (
                <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
                  {t.description}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => remove(t.id)}
              className="text-muted-foreground transition-colors hover:text-foreground"
              aria-label="Dismiss notification"
            >
              <X className="size-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
