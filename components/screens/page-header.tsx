import { cn } from '@/lib/utils'
import { ModeSwitcher } from './mode-switcher'

export function PageHeader({
  eyebrow,
  title,
  description,
  className,
  showModeSwitcher = true,
}: {
  eyebrow?: string
  title: string
  description?: string
  className?: string
  showModeSwitcher?: boolean
}) {
  return (
    <div className={cn('mb-8', className)}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && (
            <p className="mb-2 text-sm font-semibold text-primary">{eyebrow}</p>
          )}
          <h1 className="text-2xl font-bold tracking-tight text-foreground text-balance sm:text-3xl">
            {title}
          </h1>
        </div>
        {showModeSwitcher && <ModeSwitcher />}
      </div>
      {description && (
        <p className="mt-2 max-w-2xl text-base leading-relaxed text-muted-foreground text-pretty">
          {description}
        </p>
      )}
    </div>
  )
}
