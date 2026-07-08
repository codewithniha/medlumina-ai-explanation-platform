import { cn } from '@/lib/utils'

export function PageHeader({
  eyebrow,
  title,
  description,
  className,
}: {
  eyebrow?: string
  title: string
  description?: string
  className?: string
}) {
  return (
    <div className={cn('mb-8', className)}>
      {eyebrow && (
        <p className="mb-2 text-sm font-semibold text-primary">{eyebrow}</p>
      )}
      <h1 className="text-2xl font-bold tracking-tight text-foreground text-balance sm:text-3xl">
        {title}
      </h1>
      {description && (
        <p className="mt-2 max-w-2xl text-base leading-relaxed text-muted-foreground text-pretty">
          {description}
        </p>
      )}
    </div>
  )
}
