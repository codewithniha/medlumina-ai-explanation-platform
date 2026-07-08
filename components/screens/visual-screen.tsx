'use client'

import { useState, useRef } from 'react'
import { Eye, Info, ArrowRight, MoveHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { PageHeader } from './page-header'
import { useApp } from '@/lib/app-context'
import { mockReport } from '@/lib/mock-data'

function Heatmap() {
  const { heatmap } = mockReport
  return (
    <div
      className="pointer-events-none absolute"
      style={{
        top: `${heatmap.top}%`,
        left: `${heatmap.left}%`,
        width: `${heatmap.width}%`,
        height: `${heatmap.height}%`,
      }}
    >
      <div className="absolute inset-0 rounded-full bg-red-500/50 blur-xl" />
      <div className="absolute inset-[15%] rounded-full bg-orange-400/50 blur-lg" />
      <div className="absolute inset-[35%] rounded-full bg-yellow-300/60 blur-md" />
      <div className="absolute inset-0 rounded-full border-2 border-red-400/70" />
    </div>
  )
}

export function VisualScreen() {
  const { navigate } = useApp()
  const [showOverlay, setShowOverlay] = useState(true)
  const [sliderPos, setSliderPos] = useState(50)
  const containerRef = useRef<HTMLDivElement>(null)

  function handleMove(clientX: number) {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    const pct = ((clientX - rect.left) / rect.width) * 100
    setSliderPos(Math.max(0, Math.min(100, pct)))
  }

  return (
    <div>
      <PageHeader
        eyebrow="Explainability"
        title="Visual Explanation"
        description="Drag the slider to compare your original X-ray with the AI's highlighted view. The colored area shows where the finding is."
      />

      <Card className="mb-6 overflow-hidden">
        <CardContent className="p-4 sm:p-6">
          {/* Comparison slider */}
          <div
            ref={containerRef}
            className="relative aspect-square w-full max-w-xl mx-auto select-none overflow-hidden rounded-2xl bg-neutral-900"
            onMouseMove={(e) => e.buttons === 1 && handleMove(e.clientX)}
            onTouchMove={(e) => handleMove(e.touches[0].clientX)}
          >
            {/* Base: original */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/chest-xray.png"
              alt="Original chest X-ray"
              className="absolute inset-0 size-full object-cover"
              draggable={false}
            />

            {/* Annotated side (clipped to slider) */}
            <div
              className="absolute inset-0 overflow-hidden"
              style={{ clipPath: `inset(0 0 0 ${sliderPos}%)` }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/chest-xray.png"
                alt="Annotated chest X-ray with highlighted region"
                className="absolute inset-0 size-full object-cover"
                draggable={false}
              />
              {showOverlay && <Heatmap />}
            </div>

            {/* Labels */}
            <Badge
              variant="secondary"
              className="absolute left-3 top-3 bg-black/50 text-white backdrop-blur"
            >
              Original
            </Badge>
            <Badge className="absolute right-3 top-3 bg-red-500/80 text-white">
              AI Highlighted
            </Badge>

            {/* Slider handle */}
            <div
              className="absolute inset-y-0 w-0.5 bg-white/90"
              style={{ left: `${sliderPos}%` }}
            >
              <div className="absolute top-1/2 left-1/2 flex size-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white text-neutral-800 shadow-lg">
                <MoveHorizontal className="size-4" />
              </div>
            </div>

            {/* Range input for accessibility / dragging */}
            <input
              type="range"
              min={0}
              max={100}
              value={sliderPos}
              onChange={(e) => setSliderPos(Number(e.target.value))}
              className="absolute inset-0 size-full cursor-ew-resize opacity-0"
              aria-label="Compare original and highlighted X-ray"
            />
          </div>

          {/* Overlay toggle */}
          <div className="mt-4 flex items-center justify-center gap-3 rounded-xl bg-secondary/50 p-3">
            <Eye className="size-4 text-primary" />
            <span className="text-sm font-medium text-foreground">
              Show highlighted region
            </span>
            <Switch
              checked={showOverlay}
              onCheckedChange={setShowOverlay}
              aria-label="Toggle highlighted region overlay"
            />
          </div>
        </CardContent>
      </Card>

      {/* Caption */}
      <Card className="mb-8 border-primary/20 bg-primary/5">
        <CardContent className="flex gap-3 p-5">
          <Info className="mt-0.5 size-5 shrink-0 text-primary" />
          <div>
            <p className="text-sm font-semibold text-foreground">
              What the highlight means
            </p>
            <p className="mt-1 text-[15px] leading-relaxed text-foreground/90 text-pretty">
              {mockReport.visualCaption}
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button
          size="lg"
          className="h-12 px-6 text-base"
          onClick={() => navigate('qa')}
        >
          Ask About This
          <ArrowRight className="size-4" />
        </Button>
        <Button
          size="lg"
          variant="outline"
          className="h-12 px-6 text-base"
          onClick={() => navigate('medicine')}
        >
          View Medicine & Symptoms
        </Button>
      </div>
    </div>
  )
}
