'use client'

import { useEffect, useState } from 'react'

export function ConfidenceRing({
  value,
  size = 132,
}: {
  value: number
  size?: number
}) {
  const stroke = 11
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const [display, setDisplay] = useState(0)

  // Animate the counter and the arc on mount.
  useEffect(() => {
    let frame: number
    const start = performance.now()
    const duration = 1100
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      setDisplay(Math.round(eased * value))
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])

  const offset = circumference - (display / 100) * circumference

  return (
    <div
      className="relative flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Confidence score ${value} percent`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id="confGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--color-chart-3)" />
            <stop offset="100%" stopColor="var(--color-primary)" />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="stroke-muted"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          stroke="url(#confGradient)"
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="text-[28px] font-bold leading-none text-foreground tabular-nums">
          {display}%
        </span>
        <span className="mt-1 text-[11px] font-medium text-muted-foreground">
          AI confidence
        </span>
      </div>
    </div>
  )
}
