'use client'

import { Repeat, FileText, ScanLine, Pill } from 'lucide-react'
import { useApp, type InputMode } from '@/lib/app-context'

const modeMeta: Record<
  InputMode,
  { label: string; icon: React.ComponentType<{ className?: string }> }
> = {
  xray_report: { label: 'X-ray + Report', icon: FileText },
  xray_only: { label: 'X-ray only', icon: ScanLine },
  prescription_only: { label: 'Prescription only', icon: Pill },
}

// A persistent control so a patient who picked the wrong path can switch
// without losing their whole session. It returns them to the Upload step where
// the full mode selector lives.
export function ModeSwitcher() {
  const { session, navigate } = useApp()
  const meta = modeMeta[session.inputMode]
  const Icon = meta.icon

  return (
    <div className="flex shrink-0 items-center gap-2 rounded-full border border-border bg-card/60 py-1 pl-3 pr-1">
      <span className="hidden items-center gap-1.5 text-xs font-medium text-muted-foreground sm:flex">
        <Icon className="size-3.5 text-primary" />
        {meta.label}
      </span>
      <button
        type="button"
        onClick={() => navigate('input')}
        className="flex items-center gap-1.5 rounded-full bg-muted px-3 py-1.5 text-xs font-semibold text-foreground transition-colors hover:bg-primary/10 hover:text-primary"
      >
        <Repeat className="size-3.5" />
        Change input type
      </button>
    </div>
  )
}
