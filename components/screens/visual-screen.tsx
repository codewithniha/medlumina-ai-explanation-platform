'use client'

import { useState, useRef, useCallback } from 'react'
import {
  Eye,
  EyeOff,
  Info,
  ArrowRight,
  MoveHorizontal,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minimize2,
  RotateCcw,
  MapPin,
  Layers,
  SlidersHorizontal,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { PageHeader } from './page-header'
import { useApp } from '@/lib/app-context'
import { mockReport } from '@/lib/mock-data'
import { cn } from '@/lib/utils'

function Heatmap({ opacity, intensity }: { opacity: number; intensity: number }) {
  const { heatmap } = mockReport
  // intensity (0..100) subtly scales the glow spread.
  const scale = 0.8 + (intensity / 100) * 0.6
  return (
    <div
      className="pointer-events-none absolute transition-opacity duration-200"
      style={{
        top: `${heatmap.top}%`,
        left: `${heatmap.left}%`,
        width: `${heatmap.width}%`,
        height: `${heatmap.height}%`,
        opacity: opacity / 100,
        transform: `scale(${scale})`,
      }}
    >
      <div className="absolute inset-0 rounded-full bg-red-500/50 blur-xl" />
      <div className="absolute inset-[15%] rounded-full bg-orange-400/50 blur-lg" />
      <div className="absolute inset-[35%] rounded-full bg-yellow-300/60 blur-md" />
      <div className="absolute inset-0 rounded-full border-2 border-red-400/70" />
    </div>
  )
}

function Annotation() {
  const { heatmap } = mockReport
  return (
    <div
      className="pointer-events-none absolute z-10"
      style={{
        top: `${heatmap.top + heatmap.height / 2}%`,
        left: `${heatmap.left + heatmap.width / 2}%`,
      }}
    >
      <div className="flex -translate-x-1/2 -translate-y-full flex-col items-center">
        <span className="whitespace-nowrap rounded-lg border border-red-400/50 bg-black/70 px-2.5 py-1 text-[11px] font-semibold text-white backdrop-blur">
          Opacity — left lower lobe
        </span>
        <MapPin className="mt-0.5 size-5 text-red-400 drop-shadow" />
      </div>
    </div>
  )
}

function ControlSlider({
  icon: Icon,
  label,
  value,
  onChange,
  disabled,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  onChange: (v: number) => void
  disabled?: boolean
}) {
  return (
    <div className={cn(disabled && 'opacity-40')}>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
          <Icon className="size-3.5 text-primary" />
          {label}
        </span>
        <span className="text-xs font-semibold tabular-nums text-muted-foreground">
          {value}%
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
        aria-label={label}
      />
    </div>
  )
}

export function VisualScreen() {
  const { navigate } = useApp()
  const [showOverlay, setShowOverlay] = useState(true)
  const [showAnnotation, setShowAnnotation] = useState(true)
  const [compareMode, setCompareMode] = useState(false)
  const [sliderPos, setSliderPos] = useState(50)
  const [opacity, setOpacity] = useState(80)
  const [intensity, setIntensity] = useState(60)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [fullscreen, setFullscreen] = useState(false)

  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<HTMLDivElement>(null)
  const dragState = useRef<{ x: number; y: number; px: number; py: number } | null>(
    null,
  )

  function handleSliderMove(clientX: number) {
    const rect = viewerRef.current?.getBoundingClientRect()
    if (!rect) return
    const pct = ((clientX - rect.left) / rect.width) * 100
    setSliderPos(Math.max(0, Math.min(100, pct)))
  }

  const startPan = useCallback(
    (clientX: number, clientY: number) => {
      if (zoom <= 1 || compareMode) return
      dragState.current = { x: clientX, y: clientY, px: pan.x, py: pan.y }
    },
    [zoom, pan, compareMode],
  )

  const movePan = useCallback((clientX: number, clientY: number) => {
    if (!dragState.current) return
    const dx = clientX - dragState.current.x
    const dy = clientY - dragState.current.y
    setPan({ x: dragState.current.px + dx, y: dragState.current.py + dy })
  }, [])

  function resetView() {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }

  async function toggleFullscreen() {
    const el = containerRef.current
    if (!el) return
    if (!document.fullscreenElement) {
      await el.requestFullscreen?.()
      setFullscreen(true)
    } else {
      await document.exitFullscreen?.()
      setFullscreen(false)
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Step 3 of 6"
        title="Visual Explanation"
        description="Explore your X-ray with zoom, overlays, and a side-by-side comparison. The colored area shows where the finding is."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Viewer */}
        <div className="lg:col-span-8">
          <Card className="overflow-hidden">
            <div ref={containerRef} className="bg-neutral-950">
              <div
                ref={viewerRef}
                className={cn(
                  'relative aspect-square w-full select-none overflow-hidden',
                  zoom > 1 && !compareMode
                    ? 'cursor-grab active:cursor-grabbing'
                    : compareMode
                      ? 'cursor-ew-resize'
                      : 'cursor-default',
                  fullscreen && 'h-dvh',
                )}
                onMouseDown={(e) => {
                  if (compareMode) handleSliderMove(e.clientX)
                  else startPan(e.clientX, e.clientY)
                }}
                onMouseMove={(e) => {
                  if (compareMode && e.buttons === 1) handleSliderMove(e.clientX)
                  else if (e.buttons === 1) movePan(e.clientX, e.clientY)
                }}
                onMouseUp={() => (dragState.current = null)}
                onMouseLeave={() => (dragState.current = null)}
                onTouchMove={(e) => {
                  if (compareMode) handleSliderMove(e.touches[0].clientX)
                }}
              >
                <div
                  className="absolute inset-0 transition-transform duration-100"
                  style={{
                    transform: compareMode
                      ? undefined
                      : `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                  }}
                >
                  {/* Base image */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src="/chest-xray.png"
                    alt="Original chest X-ray"
                    className="absolute inset-0 size-full object-cover"
                    draggable={false}
                  />

                  {compareMode ? (
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
                      {showOverlay && (
                        <Heatmap opacity={opacity} intensity={intensity} />
                      )}
                    </div>
                  ) : (
                    <>
                      {showOverlay && (
                        <Heatmap opacity={opacity} intensity={intensity} />
                      )}
                      {showAnnotation && <Annotation />}
                    </>
                  )}
                </div>

                {/* Labels */}
                <Badge
                  variant="secondary"
                  className="absolute left-3 top-3 bg-black/50 text-white backdrop-blur"
                >
                  {compareMode ? 'Original' : 'X-ray view'}
                </Badge>
                {compareMode && (
                  <Badge className="absolute right-3 top-3 bg-red-500/80 text-white">
                    AI Highlighted
                  </Badge>
                )}

                {/* Compare slider handle */}
                {compareMode && (
                  <div
                    className="pointer-events-none absolute inset-y-0 w-0.5 bg-white/90"
                    style={{ left: `${sliderPos}%` }}
                  >
                    <div className="absolute left-1/2 top-1/2 flex size-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white text-neutral-800 shadow-lg">
                      <MoveHorizontal className="size-4" />
                    </div>
                  </div>
                )}

                {/* Floating toolbar */}
                <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full border border-white/10 bg-black/50 px-1.5 py-1.5 backdrop-blur">
                  <IconBtn
                    label="Zoom out"
                    onClick={() => setZoom((z) => Math.max(1, +(z - 0.5).toFixed(1)))}
                    disabled={compareMode || zoom <= 1}
                  >
                    <ZoomOut className="size-4" />
                  </IconBtn>
                  <span className="min-w-10 text-center text-xs font-semibold tabular-nums text-white">
                    {Math.round(zoom * 100)}%
                  </span>
                  <IconBtn
                    label="Zoom in"
                    onClick={() => setZoom((z) => Math.min(4, +(z + 0.5).toFixed(1)))}
                    disabled={compareMode || zoom >= 4}
                  >
                    <ZoomIn className="size-4" />
                  </IconBtn>
                  <span className="mx-0.5 h-5 w-px bg-white/20" />
                  <IconBtn label="Reset view" onClick={resetView} disabled={compareMode}>
                    <RotateCcw className="size-4" />
                  </IconBtn>
                  <IconBtn label="Fullscreen" onClick={toggleFullscreen}>
                    {fullscreen ? (
                      <Minimize2 className="size-4" />
                    ) : (
                      <Maximize2 className="size-4" />
                    )}
                  </IconBtn>
                </div>
              </div>
            </div>
          </Card>

          {/* Legend */}
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-border bg-card/60 px-4 py-3">
            <span className="text-xs font-semibold text-foreground">Legend</span>
            <LegendDot className="bg-red-500/80" label="High attention" />
            <LegendDot className="bg-orange-400/80" label="Moderate" />
            <LegendDot className="bg-yellow-300/80" label="Low / edge" />
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <MapPin className="size-3.5 text-red-400" />
              Annotated finding
            </span>
          </div>
        </div>

        {/* Controls */}
        <div className="space-y-4 lg:col-span-4">
          <Card>
            <CardContent className="space-y-4 p-5">
              <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
                <SlidersHorizontal className="size-4 text-primary" />
                Display controls
              </h3>

              <ToggleRow
                icon={compareMode ? Layers : Eye}
                label="Comparison slider"
                checked={compareMode}
                onChange={(v) => {
                  setCompareMode(v)
                  resetView()
                }}
              />
              <ToggleRow
                icon={showOverlay ? Eye : EyeOff}
                label="Highlighted region"
                checked={showOverlay}
                onChange={setShowOverlay}
              />
              <ToggleRow
                icon={MapPin}
                label="Annotation marker"
                checked={showAnnotation}
                onChange={setShowAnnotation}
                disabled={compareMode}
              />

              <div className="h-px bg-border" />

              <ControlSlider
                icon={Eye}
                label="Overlay opacity"
                value={opacity}
                onChange={setOpacity}
                disabled={!showOverlay}
              />
              <ControlSlider
                icon={Layers}
                label="Heatmap intensity"
                value={intensity}
                onChange={setIntensity}
                disabled={!showOverlay}
              />
            </CardContent>
          </Card>

          {/* Caption */}
          <Card className="border-primary/25 bg-primary/5">
            <CardContent className="flex gap-3 p-5">
              <Info className="mt-0.5 size-5 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-semibold text-foreground">
                  What the highlight means
                </p>
                <p className="mt-1 text-sm leading-relaxed text-foreground/90 text-pretty">
                  {mockReport.visualCaption}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="mt-8 flex flex-col gap-3 sm:flex-row">
        <Button className="h-12 px-6 text-base" onClick={() => navigate('qa')}>
          Ask About This
          <ArrowRight className="size-4" />
        </Button>
        <Button
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

function IconBtn({
  children,
  label,
  onClick,
  disabled,
}: {
  children: React.ReactNode
  label: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="flex size-8 items-center justify-center rounded-full text-white transition-colors hover:bg-white/15 disabled:opacity-30 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  )
}

function ToggleRow({
  icon: Icon,
  label,
  checked,
  onChange,
  disabled,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className={cn('flex items-center justify-between', disabled && 'opacity-40')}>
      <span className="flex items-center gap-2 text-sm font-medium text-foreground">
        <Icon className="size-4 text-primary" />
        {label}
      </span>
      <Switch
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        aria-label={label}
      />
    </div>
  )
}

function LegendDot({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={cn('size-2.5 rounded-full', className)} />
      {label}
    </span>
  )
}
