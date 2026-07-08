'use client'

import { useState } from 'react'
import {
  Home,
  Upload,
  FileText,
  ScanEye,
  MessagesSquare,
  Pill,
  ClipboardCheck,
  Menu,
  X,
  Activity,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useApp, type ScreenId } from '@/lib/app-context'

type NavItem = {
  id: ScreenId
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const navItems: NavItem[] = [
  { id: 'overview', label: 'Overview', icon: Home },
  { id: 'input', label: 'New Analysis', icon: Upload },
  { id: 'report', label: 'AI Report', icon: FileText },
  { id: 'visual', label: 'Visual Explanation', icon: ScanEye },
  { id: 'qa', label: 'Ask Questions', icon: MessagesSquare },
  { id: 'medicine', label: 'Medicine & Symptoms', icon: Pill },
  { id: 'summary', label: 'Summary', icon: ClipboardCheck },
]

// Mobile bottom-nav shows the most important destinations.
const mobileItems = navItems.filter((n) =>
  ['overview', 'input', 'report', 'qa', 'summary'].includes(n.id),
)

function Brand({ className }: { className?: string }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
        <Activity className="size-5" />
      </div>
      <div className="leading-tight">
        <p className="text-base font-bold tracking-tight text-foreground">
          MedLumina
        </p>
        <p className="text-[11px] font-medium text-muted-foreground">
          X-ray, in plain language
        </p>
      </div>
    </div>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { screen, navigate } = useApp()
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="min-h-dvh bg-background lg:flex">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-72 shrink-0 flex-col border-r border-sidebar-border bg-sidebar lg:flex">
        <div className="p-6">
          <Brand />
        </div>
        <nav className="flex-1 space-y-1 px-4">
          {navItems.map((item) => {
            const active = screen === item.id
            const Icon = item.icon
            return (
              <button
                key={item.id}
                onClick={() => navigate(item.id)}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex w-full items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-colors',
                  active
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                )}
              >
                <Icon className="size-[18px] shrink-0" />
                {item.label}
              </button>
            )
          })}
        </nav>
        <div className="p-4">
          <div className="rounded-xl bg-accent/60 p-4">
            <p className="text-xs font-medium leading-relaxed text-accent-foreground">
              Demo prototype. All reports and explanations are fictional sample
              data and not medical advice.
            </p>
          </div>
        </div>
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-40 flex items-center justify-between border-b border-border bg-background/90 px-4 py-3 backdrop-blur lg:hidden">
        <Brand />
        <button
          onClick={() => setMobileOpen((v) => !v)}
          className="flex size-10 items-center justify-center rounded-xl text-foreground transition-colors hover:bg-muted"
          aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
        >
          {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </header>

      {/* Mobile slide-down menu */}
      {mobileOpen && (
        <div className="fixed inset-0 top-[61px] z-30 bg-black/20 lg:hidden" onClick={() => setMobileOpen(false)}>
          <nav
            className="space-y-1 border-b border-border bg-background p-4 shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            {navItems.map((item) => {
              const active = screen === item.id
              const Icon = item.icon
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    navigate(item.id)
                    setMobileOpen(false)
                  }}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-xl px-3.5 py-3 text-sm font-medium transition-colors',
                    active
                      ? 'bg-primary text-primary-foreground'
                      : 'text-foreground hover:bg-muted',
                  )}
                >
                  <Icon className="size-[18px] shrink-0" />
                  {item.label}
                </button>
              )
            })}
          </nav>
        </div>
      )}

      {/* Main content */}
      <main className="flex-1 pb-24 lg:pb-0">
        <div className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-6 sm:py-10">
          {children}
        </div>
      </main>

      {/* Mobile bottom nav */}
      <nav className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-border bg-background/95 px-2 py-2 backdrop-blur lg:hidden">
        {mobileItems.map((item) => {
          const active = screen === item.id
          const Icon = item.icon
          return (
            <button
              key={item.id}
              onClick={() => navigate(item.id)}
              className={cn(
                'flex flex-1 flex-col items-center gap-1 rounded-lg py-1.5 text-[11px] font-medium transition-colors',
                active ? 'text-primary' : 'text-muted-foreground',
              )}
              aria-current={active ? 'page' : undefined}
            >
              <Icon className="size-5" />
              {item.label.split(' ')[0]}
            </button>
          )
        })}
      </nav>
    </div>
  )
}
