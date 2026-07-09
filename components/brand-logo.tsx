import { cn } from '@/lib/utils'
import { Activity } from 'lucide-react'

export function BrandLogo({
  className,
  showTagline = true,
  size = 'md',
}: {
  className?: string
  showTagline?: boolean
  size?: 'sm' | 'md'
}) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <div
        className={cn(
          'flex items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-[0_0_20px_-4px_var(--color-primary)]',
          size === 'md' ? 'size-9' : 'size-8',
        )}
      >
        <Activity className={size === 'md' ? 'size-5' : 'size-4'} />
      </div>
      <div className="leading-tight">
        <p
          className={cn(
            'font-bold tracking-tight text-foreground',
            size === 'md' ? 'text-base' : 'text-sm',
          )}
        >
          MedLumina
        </p>
        {showTagline && (
          <p className="text-[11px] font-medium text-muted-foreground">
            X-ray, in plain language
          </p>
        )}
      </div>
    </div>
  )
}
