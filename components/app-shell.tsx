'use client'

import { useState } from 'react'
import {
  Upload,
  FileText,
  ScanEye,
  MessagesSquare,
  Pill,
  ClipboardCheck,
  Menu,
  X,
  Home,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  Check,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useApp, type ScreenId, type InputMode } from '@/lib/app-context'
import { BrandLogo } from '@/components/brand-logo'

type NavItem = {
  id: ScreenId
  label: string
  icon: React.ComponentType<{ className?: string }>
}

// Per-step icon plus a default label and any mode-specific label overrides.
// The sidebar is built from the active mode's step list (see lib/app-context),
// so steps that don't apply to a mode are removed entirely, not disabled.
const stepMeta: Record<
  Exclude<ScreenId, 'landing'>,
  {
    icon: React.ComponentType<{ className?: string }>
    label: string
    labelByMode?: Partial<Record<InputMode, string>>
  }
> = {
  input: {
    icon: Upload,
    label: 'Upload X-ray',
    labelByMode: { prescription_only: 'Upload Prescription' },
  },
  report: {
    icon: FileText,
    label: 'AI Report',
    labelByMode: {
      xray_report: 'Your Report',
      prescription_only: 'Medicine & Condition',
    },
  },
  visual: { icon: ScanEye, label: 'Visual Explanation' },
  qa: { icon: MessagesSquare, label: 'Ask Questions' },
  medicine: { icon: Pill, label: 'Medicine & Symptoms' },
  summary: { icon: ClipboardCheck, label: 'Summary' },
}

function buildNav(mode: InputMode, steps: ScreenId[]): NavItem[] {
  return steps.map((id) => {
    const meta = stepMeta[id as Exclude<ScreenId, 'landing'>]
    return {
      id,
      icon: meta.icon,
      label: meta.labelByMode?.[mode] ?? meta.label,
    }
  })
}

function ProgressCard({ collapsed }: { collapsed: boolean }) {
  const { progress, completedSteps, steps } = useApp()
  if (collapsed) {
    return (
      <div className="mx-auto flex size-9 items-center justify-center rounded-lg bg-primary/10 text-xs font-bold text-primary">
        {progress}
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-border bg-card/60 p-3.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-foreground">
          Your progress
        </span>
        <span className="text-xs font-bold text-primary">{progress}%</span>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        {completedSteps.length} of {steps.length} steps explored
      </p>
    </div>
  )
}

function NavButton({
  item,
  index,
  active,
  completed,
  collapsed,
  onClick,
}: {
  item: NavItem
  index: number
  active: boolean
  completed: boolean
  collapsed: boolean
  onClick: () => void
}) {
  const Icon = item.icon
  return (
    <button
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      title={collapsed ? item.label : undefined}
      className={cn(
        'group relative flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200',
        collapsed && 'justify-center px-0',
        active
          ? 'bg-primary text-primary-foreground shadow-[0_4px_16px_-4px_var(--color-primary)]'
          : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
      )}
    >
      {active && !collapsed && (
        <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-primary-foreground/80" />
      )}
      <span className="relative flex size-5 shrink-0 items-center justify-center">
        <Icon className="size-[18px]" />
        {completed && !active && (
          <span className="absolute -right-1.5 -top-1.5 flex size-3 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Check className="size-2" />
          </span>
        )}
      </span>
      {!collapsed && <span className="flex-1 text-left">{item.label}</span>}
      {!collapsed && (
        <span
          className={cn(
            'text-[11px] font-semibold tabular-nums',
            active ? 'text-primary-foreground/70' : 'text-muted-foreground/60',
          )}
        >
          {index + 1}
        </span>
      )}
    </button>
  )
}

function SidebarContent({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean
  onNavigate?: () => void
}) {
  const { screen, navigate, completedSteps, session, steps } = useApp()
  const workflowNav = buildNav(session.inputMode, steps)
  return (
    <>
      <nav className="flex-1 overflow-y-auto px-3">
        {/* General group */}
        {!collapsed && (
          <p className="px-3 pb-2 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            General
          </p>
        )}
        <div className={cn('space-y-1', collapsed && 'pt-4')}>
          <button
            onClick={() => {
              navigate('landing')
              onNavigate?.()
            }}
            title={collapsed ? 'Home' : undefined}
            className={cn(
              'flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-sidebar-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
              collapsed && 'justify-center px-0',
            )}
          >
            <Home className="size-[18px] shrink-0" />
            {!collapsed && 'Home'}
          </button>
        </div>

        {/* Workflow group */}
        {!collapsed && (
          <p className="px-3 pb-2 pt-5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            Workflow
          </p>
        )}
        <div className={cn('space-y-1', collapsed && 'pt-2')}>
          {workflowNav.map((item, i) => (
            <NavButton
              key={item.id}
              item={item}
              index={i}
              active={screen === item.id}
              completed={completedSteps.includes(item.id)}
              collapsed={collapsed}
              onClick={() => {
                navigate(item.id)
                onNavigate?.()
              }}
            />
          ))}
        </div>

      </nav>

      {/* Footer: progress + profile */}
      <div className="space-y-3 border-t border-sidebar-border p-3">
        <ProgressCard collapsed={collapsed} />
        <button
          title={collapsed ? 'Settings' : undefined}
          className={cn(
            'flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-sidebar-foreground transition-colors hover:bg-sidebar-accent',
            collapsed && 'justify-center px-0',
          )}
        >
          <Settings className="size-[18px] shrink-0" />
          {!collapsed && 'Settings'}
        </button>
        <div
          className={cn(
            'flex items-center gap-3 rounded-xl border border-sidebar-border bg-card/60 p-2.5',
            collapsed && 'justify-center border-0 bg-transparent p-0',
          )}
        >
          <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-bold text-primary">
            AP
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-sidebar-foreground">
                Alex Patient
              </p>
              <p className="truncate text-[11px] text-muted-foreground">
                Demo account
              </p>
            </div>
          )}
        </div>
      </div>
    </>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { screen, session, steps } = useApp()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  // Mobile bottom-nav mirrors the active mode's steps (skipping the deep
  // "medicine" step to keep the bar compact when it exists).
  const mobileItems = buildNav(session.inputMode, steps).filter(
    (n) => n.id !== 'medicine',
  )

  return (
    <div className="min-h-dvh bg-background lg:flex">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          'sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-300 ease-out lg:flex',
          collapsed ? 'w-20' : 'w-72',
        )}
      >
        <div
          className={cn(
            'flex items-center gap-2 p-4',
            collapsed ? 'justify-center' : 'justify-between',
          )}
        >
          {!collapsed && <BrandLogo />}
          <button
            onClick={() => setCollapsed((v) => !v)}
            className="flex size-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? (
              <PanelLeftOpen className="size-5" />
            ) : (
              <PanelLeftClose className="size-5" />
            )}
          </button>
        </div>
        <SidebarContent collapsed={collapsed} />
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-40 flex items-center justify-between border-b border-border bg-background/80 px-4 py-3 backdrop-blur-xl lg:hidden">
        <BrandLogo />
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
        <div
          className="fixed inset-0 top-[57px] z-30 bg-black/50 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
        >
          <div
            className="flex max-h-[calc(100dvh-57px)] flex-col overflow-hidden border-b border-border bg-sidebar shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <SidebarContent
              collapsed={false}
              onNavigate={() => setMobileOpen(false)}
            />
          </div>
        </div>
      )}

      {/* Main content */}
      <main className="flex-1 pb-24 lg:pb-0">
        <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-10 lg:py-12">
          {children}
        </div>
      </main>

      {/* Mobile bottom nav */}
      <nav className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-border bg-background/95 px-2 py-2 backdrop-blur-xl lg:hidden">
        {mobileItems.map((item) => {
          const active = screen === item.id
          const Icon = item.icon
          return (
            <MobileNavButton
              key={item.id}
              id={item.id}
              label={item.label}
              Icon={Icon}
              active={active}
            />
          )
        })}
      </nav>
    </div>
  )
}

function MobileNavButton({
  id,
  label,
  Icon,
  active,
}: {
  id: ScreenId
  label: string
  Icon: React.ComponentType<{ className?: string }>
  active: boolean
}) {
  const { navigate } = useApp()
  return (
    <button
      onClick={() => navigate(id)}
      className={cn(
        'flex flex-1 flex-col items-center gap-1 rounded-lg py-1.5 text-[11px] font-medium transition-colors',
        active ? 'text-primary' : 'text-muted-foreground',
      )}
      aria-current={active ? 'page' : undefined}
    >
      <Icon className="size-5" />
      {label.split(' ')[0]}
    </button>
  )
}
