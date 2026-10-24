'use client'

import { useRef } from 'react'

// One circle on the model's SQUARE-padded X-ray, in pixels of that square (side = `canvas`).
export type Circle = { cx: number; cy: number; r: number }

export type EditorItem = { key: string; label: string; color: string; circles: Circle[] }

// Same colours, same order as the picture the server draws (module5_draw.PALETTE).
export const PALETTE_HEX = ['#ff3c3c', '#00c8ff', '#ffc800', '#50ff78', '#ff00c8', '#aa82ff', '#ff9600', '#64ffff']

const MIN_R = 4

type Drag = { mode: 'move' | 'resize'; key: string; i: number; dx: number; dy: number }

// A square picture of the X-ray with draggable circles on top. The picture is shown with
// object-contain inside a black square, which is exactly how the model's padded square is built,
// so a circle's coordinates are the same numbers the server stores and redraws.
export function RegionEditor({
  imageUrl,
  canvas,
  items,
  selected,
  onSelect,
  onChange,
}: {
  imageUrl: string | null
  canvas: number
  items: EditorItem[]
  selected: { key: string; i: number } | null
  onSelect: (s: { key: string; i: number } | null) => void
  onChange: (key: string, circles: Circle[]) => void
}) {
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<Drag | null>(null)
  const stroke = Math.max(2, canvas * 0.005)
  const handleR = Math.max(7, canvas * 0.018)

  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

  function toSvg(e: React.PointerEvent): { x: number; y: number } {
    const svg = svgRef.current
    const m = svg?.getScreenCTM()
    if (!svg || !m) return { x: 0, y: 0 }
    const pt = svg.createSVGPoint()
    pt.x = e.clientX
    pt.y = e.clientY
    const p = pt.matrixTransform(m.inverse())
    return { x: p.x, y: p.y }
  }

  function circlesOf(key: string): Circle[] {
    return items.find((it) => it.key === key)?.circles ?? []
  }

  function replace(key: string, i: number, next: Circle) {
    onChange(key, circlesOf(key).map((c, j) => (j === i ? next : c)))
  }

  function begin(e: React.PointerEvent, mode: Drag['mode'], key: string, i: number) {
    e.stopPropagation()
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    const c = circlesOf(key)[i]
    const p = toSvg(e)
    drag.current = { mode, key, i, dx: p.x - c.cx, dy: p.y - c.cy }
    onSelect({ key, i })
    svgRef.current?.focus()
  }

  function moveDrag(e: React.PointerEvent) {
    const d = drag.current
    if (!d) return
    const c = circlesOf(d.key)[d.i]
    if (!c) return
    const p = toSvg(e)
    if (d.mode === 'move') {
      replace(d.key, d.i, { ...c, cx: Math.round(clamp(p.x - d.dx, 0, canvas)), cy: Math.round(clamp(p.y - d.dy, 0, canvas)) })
    } else {
      const r = Math.hypot(p.x - c.cx, p.y - c.cy)
      replace(d.key, d.i, { ...c, r: Math.round(clamp(r, MIN_R, canvas / 2)) })
    }
  }

  function endDrag() {
    drag.current = null
  }

  // Keyboard: arrows move the selected circle, + / - resize it, Delete removes it.
  function onKeyDown(e: React.KeyboardEvent) {
    if (!selected) return
    const c = circlesOf(selected.key)[selected.i]
    if (!c) return
    const step = e.shiftKey ? 20 : 4
    let next: Circle | null = null
    if (e.key === 'ArrowLeft') next = { ...c, cx: clamp(c.cx - step, 0, canvas) }
    else if (e.key === 'ArrowRight') next = { ...c, cx: clamp(c.cx + step, 0, canvas) }
    else if (e.key === 'ArrowUp') next = { ...c, cy: clamp(c.cy - step, 0, canvas) }
    else if (e.key === 'ArrowDown') next = { ...c, cy: clamp(c.cy + step, 0, canvas) }
    else if (e.key === '+' || e.key === '=') next = { ...c, r: clamp(c.r + step, MIN_R, canvas / 2) }
    else if (e.key === '-' || e.key === '_') next = { ...c, r: clamp(c.r - step, MIN_R, canvas / 2) }
    else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault()
      onChange(selected.key, circlesOf(selected.key).filter((_, j) => j !== selected.i))
      onSelect(null)
      return
    }
    if (next) {
      e.preventDefault()
      replace(selected.key, selected.i, next)
    }
  }

  return (
    <div className="relative aspect-square w-full max-w-lg overflow-hidden rounded-lg border bg-black">
      {imageUrl && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={imageUrl} alt="X-ray to mark" draggable={false} className="absolute inset-0 h-full w-full select-none object-contain" />
      )}
      <svg
        ref={svgRef}
        data-testid="region-canvas"
        role="application"
        aria-label="Circle editor. Select a circle, then use arrow keys to move it, plus and minus to resize, Delete to remove."
        tabIndex={0}
        viewBox={`0 0 ${canvas} ${canvas}`}
        preserveAspectRatio="xMidYMid meet"
        className="absolute inset-0 h-full w-full touch-none outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onKeyDown={onKeyDown}
        onPointerDown={() => onSelect(null)}
      >
        {items.map((it) =>
          it.circles.map((c, i) => {
            const isSel = selected?.key === it.key && selected.i === i
            return (
              <g key={`${it.key}-${i}`}>
                <circle
                  data-testid={`circle-${it.key}-${i}`}
                  cx={c.cx}
                  cy={c.cy}
                  r={c.r}
                  fill="transparent"
                  stroke={it.color}
                  strokeWidth={isSel ? stroke * 2 : stroke}
                  pointerEvents="all"
                  className="cursor-move"
                  onPointerDown={(e) => begin(e, 'move', it.key, i)}
                  onPointerMove={moveDrag}
                  onPointerUp={endDrag}
                  onPointerCancel={endDrag}
                />
                {isSel && (
                  <circle
                    data-testid={`handle-${it.key}-${i}`}
                    cx={c.cx + c.r}
                    cy={c.cy}
                    r={handleR}
                    fill={it.color}
                    stroke="#000"
                    strokeWidth={stroke / 2}
                    className="cursor-ew-resize"
                    onPointerDown={(e) => begin(e, 'resize', it.key, i)}
                    onPointerMove={moveDrag}
                    onPointerUp={endDrag}
                    onPointerCancel={endDrag}
                  />
                )}
              </g>
            )
          }),
        )}
      </svg>
    </div>
  )
}
