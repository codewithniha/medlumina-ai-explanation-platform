'use client'

import { useEffect, useState } from 'react'
import { ArrowLeft, Download, FolderOpen, Loader2, Pencil, Plus, Stethoscope, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from './page-header'
import { PALETTE_HEX, RegionEditor, type Circle } from './region-editor'
import {
  ApiError,
  downloadDicom,
  editDoctorFindings,
  fetchVisitImageUrl,
  getDoctorVisit,
  listRecords,
  listVisits,
  renderDicom,
  type DoctorVisitView,
  type RecordSummary,
  type VisitListItem,
} from '@/lib/api-client'

function when(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function label(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function pct(p: number | undefined): string {
  return typeof p === 'number' ? `${(p * 100).toFixed(1)}%` : '—'
}

type Images = { xray: string | null; annotated: string | null; comparison: string | null }

// A sensible starting window: the file's own if it has one, otherwise the full range of its bit depth.
function defaultWindow(center: number | null, width: number | null, bits: number | null) {
  const full = 2 ** (bits || 12)
  if (center != null && width != null && width >= 1) return { center, width }
  return { center: full / 2, width: full }
}

function windowBounds(bits: number | null, wl: { center: number; width: number }) {
  const full = 2 ** (bits || 12)
  return {
    min: Math.floor(Math.min(0, wl.center - wl.width)),
    max: Math.ceil(Math.max(full, wl.center + wl.width)),
  }
}

const MAX_ADDED = 10
const MAX_NOTE = 2000
const MAX_CIRCLES = 5

// Same rule the server uses to turn a typed finding name into its key.
function keyOf(name: string): string {
  return name.trim().toLowerCase().replace(/[\s-]+/g, '_')
}

// Doctor Dashboard. Everything shown here comes from routes that the SERVER only answers
// for a PMDC-verified doctor. Step 6a: the doctor can confirm or remove each finding, add one
// the AI missed, and write a note. Saving makes a NEW report version; the AI's stays in the history.
export function DoctorScreen() {
  const [records, setRecords] = useState<RecordSummary[] | null>(null)
  const [openRecord, setOpenRecord] = useState<RecordSummary | null>(null)
  const [visits, setVisits] = useState<VisitListItem[] | null>(null)
  const [review, setReview] = useState<DoctorVisitView | null>(null)
  const [images, setImages] = useState<Images | null>(null)
  const [loadingVisit, setLoadingVisit] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // DICOM window/level viewer state (only used when the visit has a kept DICOM original)
  const [wl, setWl] = useState<{ center: number; width: number } | null>(null)
  const [wlTouched, setWlTouched] = useState(false)
  const [invert, setInvert] = useState(false)
  const [viewerUrl, setViewerUrl] = useState<string | null>(null)
  const [rendering, setRendering] = useState(false)
  // Edit mode (step 6a)
  const [editing, setEditing] = useState(false)
  const [decisions, setDecisions] = useState<Record<string, 'confirm' | 'remove'>>({})
  const [added, setAdded] = useState<string[]>([])
  const [addText, setAddText] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  // Circle editing (step 6b-2): draft circles per finding, the snapshot taken when editing began,
  // which finding new circles go to, and which circle is selected.
  const [circles, setCircles] = useState<Record<string, Circle[]>>({})
  const [circles0, setCircles0] = useState<Record<string, Circle[]>>({})
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const [selected, setSelected] = useState<{ key: string; i: number } | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)

  useEffect(() => {
    listRecords()
      .then(setRecords)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load records.'))
  }, [])

  // Free the blob: URLs when the review view is replaced or closed.
  useEffect(() => {
    return () => {
      if (images) {
        for (const u of Object.values(images)) if (u) URL.revokeObjectURL(u)
      }
    }
  }, [images])

  // Re-render from the stored DICOM shortly after the sliders stop moving.
  useEffect(() => {
    if (!review?.dicom || !wl || !wlTouched) return
    const sessionId = review.visit.session_id
    let cancelled = false
    const t = setTimeout(async () => {
      setRendering(true)
      try {
        const url = await renderDicom(sessionId, wl.center, wl.width, invert)
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        setViewerUrl((old) => {
          if (old) URL.revokeObjectURL(old)
          return url
        })
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Could not re-render the image.')
      } finally {
        if (!cancelled) setRendering(false)
      }
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
  }, [wl, invert, wlTouched, review])

  function resetViewer() {
    setWlTouched(false)
    setInvert(false)
    setViewerUrl((old) => {
      if (old) URL.revokeObjectURL(old)
      return null
    })
    const d = review?.dicom
    if (d) setWl(defaultWindow(d.window_center, d.window_width, d.bits_stored))
  }

  function chooseRecord(r: RecordSummary) {
    setOpenRecord(r)
    setVisits(null)
    setError(null)
    listVisits(r.patient_code)
      .then(setVisits)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load this record.'))
  }

  // The three pictures of the CURRENT final version (an edit can replace the highlighted ones).
  async function loadImages(sessionId: string, view: DoctorVisitView): Promise<Images> {
    const [xray, annotated, comparison] = await Promise.all([
      view.files.xray ? fetchVisitImageUrl(sessionId, 'xray') : Promise.resolve(null),
      view.files.annotated ? fetchVisitImageUrl(sessionId, 'annotated') : Promise.resolve(null),
      view.files.comparison ? fetchVisitImageUrl(sessionId, 'comparison') : Promise.resolve(null),
    ])
    return { xray, annotated, comparison }
  }

  async function openReview(v: VisitListItem) {
    setLoadingVisit(v.session_id)
    setError(null)
    try {
      const view = await getDoctorVisit(v.session_id)
      setImages(await loadImages(v.session_id, view))
      setViewerUrl(null)
      setWlTouched(false)
      setInvert(false)
      setWl(view.dicom ? defaultWindow(view.dicom.window_center, view.dicom.window_width, view.dicom.bits_stored) : null)
      setReview(view)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open this visit.')
    } finally {
      setLoadingVisit(null)
    }
  }

  // Findings that will be in the new version (confirmed + added), in the order the picture lists them.
  const editableKeys: { key: string; label: string }[] = [
    ...Object.keys(review?.report?.structured?.findings ?? {})
      .filter((n) => decisions[n] === 'confirm')
      .map((n) => ({ key: n, label: label(n) })),
    ...added.map((a) => ({ key: keyOf(a), label: a.trim() })),
  ]
  const editorItems = editableKeys.map((it, idx) => ({
    key: it.key,
    label: it.label,
    color: PALETTE_HEX[idx % PALETTE_HEX.length],
    circles: circles[it.key] ?? [],
  }))
  // Only what the doctor actually changed is sent, so an untouched finding keeps the AI's own circle record.
  const changedCircles: Record<string, { center_xy: [number, number]; radius_px: number }[]> = {}
  for (const it of editableKeys) {
    const now = circles[it.key] ?? []
    const before = circles0[it.key] ?? []
    if (JSON.stringify(now) !== JSON.stringify(before)) {
      changedCircles[it.key] = now.map((c) => ({ center_xy: [Math.round(c.cx), Math.round(c.cy)], radius_px: Math.round(c.r) }))
    }
  }

  function addCircle() {
    const canvas = review?.canvas_px
    const key = activeKey && editableKeys.some((k) => k.key === activeKey) ? activeKey : editableKeys[0]?.key
    if (!canvas || !key) return
    const list = circles[key] ?? []
    if (list.length >= MAX_CIRCLES) {
      setEditError(`At most ${MAX_CIRCLES} circles per finding.`)
      return
    }
    setEditError(null)
    setCircles({ ...circles, [key]: [...list, { cx: Math.round(canvas / 2), cy: Math.round(canvas / 2), r: Math.round(canvas * 0.08) }] })
    setActiveKey(key)
    setSelected({ key, i: list.length })
  }

  function deleteSelected() {
    if (!selected) return
    setCircles({ ...circles, [selected.key]: (circles[selected.key] ?? []).filter((_, j) => j !== selected.i) })
    setSelected(null)
  }

  function resetCircles() {
    setCircles(JSON.parse(JSON.stringify(circles0)))
    setSelected(null)
  }

  function startEdit() {
    const names = Object.keys(review?.report?.structured?.findings ?? {})
    setDecisions(Object.fromEntries(names.map((n) => [n, 'confirm' as const])))
    const fromAi: Record<string, Circle[]> = Object.fromEntries(
      Object.entries(review?.report?.structured?.findings ?? {}).map(([n, f]) => [
        n,
        (f.regions ?? []).map((r) => ({ cx: r.center_xy[0], cy: r.center_xy[1], r: r.radius_px })),
      ]),
    )
    setCircles(fromAi)
    setCircles0(JSON.parse(JSON.stringify(fromAi)))
    setActiveKey(names[0] ?? null)
    setSelected(null)
    setAdded([])
    setAddText('')
    setNote('')
    setEditError(null)
    setSavedMsg(null)
    setEditing(true)
  }

  function cancelEdit() {
    setEditing(false)
    setEditError(null)
  }

  function addFinding() {
    const name = addText.trim()
    if (!name) return
    const key = keyOf(name)
    const existing = Object.keys(review?.report?.structured?.findings ?? {})
    if (existing.includes(key) || added.some((a) => keyOf(a) === key)) {
      setEditError(`"${name}" is already in the list.`)
      return
    }
    if (added.length >= MAX_ADDED) {
      setEditError(`You can add at most ${MAX_ADDED} findings in one edit.`)
      return
    }
    setEditError(null)
    setAdded([...added, name])
    setAddText('')
  }

  async function saveEdit() {
    if (!review?.report) return
    setSaving(true)
    setEditError(null)
    try {
      const updated = await editDoctorFindings(review.visit.session_id, {
        base_version_no: review.report.version_no,
        decisions,
        added,
        note: note.trim() ? note.trim() : null,
        ...(Object.keys(changedCircles).length > 0 ? { regions: changedCircles } : {}),
      })
      // The highlighted picture may have been redrawn for the new version: load the pictures again.
      setImages(await loadImages(review.visit.session_id, updated))
      setViewerUrl(null)
      setWlTouched(false)
      setReview(updated)
      setEditing(false)
      setSavedMsg(
        `Saved as version ${updated.report?.version_no}. The earlier version is kept in the history.` +
          (updated.index_ok === false
            ? ' Warning: the Q&A search could not be updated yet, so questions may still use older wording. Saving again retries it.'
            : ''),
      )
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Someone saved a newer version (or the analysis changed): show the latest and leave edit mode.
        try {
          const latest = await getDoctorVisit(review.visit.session_id)
          setImages(await loadImages(review.visit.session_id, latest))
          setReview(latest)
          setEditing(false)
        } catch {
          /* keep the edit form open */
        }
        setEditError(null)
        setError(`${e.message} The latest version is shown now; please review it and edit again if needed.`)
      } else {
        setEditError(e instanceof Error ? e.message : 'The edit could not be saved.')
      }
    } finally {
      setSaving(false)
    }
  }

  function closeReview() {
    setEditing(false)
    setSavedMsg(null)
    setReview(null)
    setImages(null)
    setWlTouched(false)
    setViewerUrl((old) => {
      if (old) URL.revokeObjectURL(old)
      return null
    })
  }

  async function saveDicom(kind: 'original' | 'deidentified') {
    if (!review) return
    try {
      await downloadDicom(review.visit.session_id, kind)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not download the DICOM file.')
    }
  }

  const header = (
    <PageHeader
      eyebrow="Verified doctor"
      title="Doctor Dashboard"
      description="Review saved analyses: X-ray, highlighted regions, findings and report. Edit the findings to save a new report version."
      showModeSwitcher={false}
    />
  )

  const errorBox = error && (
    <p role="alert" className="mb-4 rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {error}
    </p>
  )

  // ── Review view ───────────────────────────────────────────────────────────
  if (review) {
    const s = review.report?.structured
    const findings = Object.entries(s?.findings ?? {})
    const notShown = s?.diseases_qualified_not_shown ?? []
    const shown = new Set(s?.diseases_visualized ?? [])
    // Will the highlighted picture be redrawn when this doctor saves? Only if every AI finding has its circles saved.
    const picturesFollow = findings.length > 0 ? findings.every(([, f]) => Array.isArray(f.regions)) : s?.images_stale !== true
    return (
      <div>
        {header}
        {errorBox}
        <div className="space-y-5">
          <Button variant="ghost" className="h-9 px-2" onClick={closeReview}>
            <ArrowLeft className="size-4" />
            Back to visits
          </Button>

          <div>
            <p className="text-sm font-medium">Visit {when(review.visit.created_at)}</p>
            <p className="font-mono text-xs text-muted-foreground">
              {review.visit.patient_code} · {review.visit.session_id}
            </p>
          </div>

          {!review.report && (
            <Card>
              <CardContent className="p-5 text-sm text-muted-foreground">
                This visit has no saved analysis (questions only).
              </CardContent>
            </Card>
          )}

          {review.report && (
            <>
              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <CardContent className="space-y-2 p-4">
                    <p className="text-sm font-medium">Original X-ray</p>
                    {images?.xray ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={viewerUrl ?? images.xray} alt="Original X-ray" className="w-full rounded-lg border" />
                    ) : (
                      <p className="text-sm text-muted-foreground">Not available.</p>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="space-y-2 p-4">
                    <p className="text-sm font-medium">Highlighted regions</p>
                    {images?.annotated ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={images.annotated} alt="X-ray with highlighted regions" className="w-full rounded-lg border" />
                    ) : (
                      <p className="text-sm text-muted-foreground">No highlighted image was produced.</p>
                    )}
                    {s?.images_stale && (
                      <p className="text-xs text-muted-foreground">
                        This is still the AI&apos;s original picture. It does not show the doctor&apos;s edits (this visit
                        has no saved circle positions).
                      </p>
                    )}
                  </CardContent>
                </Card>
              </div>

              {review.dicom && wl && (
                <Card>
                  <CardContent className="space-y-3 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-medium">DICOM original</p>
                      <div className="flex flex-wrap gap-2">
                        <Button variant="outline" className="h-8" onClick={() => void saveDicom('original')}>
                          <Download className="size-4" /> Original
                        </Button>
                        <Button variant="outline" className="h-8" onClick={() => void saveDicom('deidentified')}>
                          <Download className="size-4" /> De-identified copy
                        </Button>
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {[
                        review.dicom.modality,
                        review.dicom.view_position && `view ${review.dicom.view_position}`,
                        review.dicom.columns_px && review.dicom.rows_px && `${review.dicom.columns_px}×${review.dicom.rows_px} px`,
                        review.dicom.bits_stored && `${review.dicom.bits_stored}-bit`,
                        review.dicom.pixel_spacing_row_mm && `${review.dicom.pixel_spacing_row_mm} mm/px`,
                        review.dicom.transfer_syntax,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                    {review.dicom.burned_in_annotation && (
                      <p className="text-xs text-destructive">
                        This image may have patient text burned into the picture. A de-identified copy cannot be made.
                      </p>
                    )}
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="space-y-1 text-xs">
                        <span className="flex justify-between">
                          <span>Window centre (brightness)</span>
                          <span className="font-mono">{Math.round(wl.center)}</span>
                        </span>
                        <input
                          type="range"
                          className="w-full"
                          min={windowBounds(review.dicom.bits_stored, wl).min}
                          max={windowBounds(review.dicom.bits_stored, wl).max}
                          value={wl.center}
                          onChange={(e) => { setWlTouched(true); setWl({ ...wl, center: Number(e.target.value) }) }}
                        />
                      </label>
                      <label className="space-y-1 text-xs">
                        <span className="flex justify-between">
                          <span>Window width (contrast)</span>
                          <span className="font-mono">{Math.round(wl.width)}</span>
                        </span>
                        <input
                          type="range"
                          className="w-full"
                          min={1}
                          max={windowBounds(review.dicom.bits_stored, wl).max * 2}
                          value={wl.width}
                          onChange={(e) => { setWlTouched(true); setWl({ ...wl, width: Math.max(1, Number(e.target.value)) }) }}
                        />
                      </label>
                    </div>
                    <div className="flex flex-wrap items-center gap-3 text-xs">
                      <label className="flex items-center gap-1.5">
                        <input type="checkbox" checked={invert} onChange={(e) => { setWlTouched(true); setInvert(e.target.checked) }} />
                        Invert
                      </label>
                      <Button variant="ghost" className="h-8 px-2" onClick={resetViewer}>Reset to the file&apos;s own window</Button>
                      {rendering && <Loader2 className="size-4 animate-spin" />}
                      <span className="text-muted-foreground">Changes only how the picture is shown above; the stored file is never altered.</span>
                    </div>
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardContent className="space-y-3 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium">Findings</p>
                    {!editing && (
                      <Button variant="outline" className="h-8" onClick={startEdit}>
                        <Pencil className="size-4" /> Edit findings
                      </Button>
                    )}
                  </div>
                  {savedMsg && !editing && (
                    <p role="status" className="rounded-xl border border-border bg-muted px-3 py-2 text-xs">
                      {savedMsg}
                    </p>
                  )}
                  {editing && (
                    <div className="space-y-4 rounded-xl border border-border p-3" aria-label="Edit findings">
                      <p className="text-xs text-muted-foreground">
                        Choose Confirm or Remove for every finding, add anything the AI missed, and write your note.
                        Saving creates a new report version that mentions only the findings you keep. The highlighted
                        picture is{' '}
                        {picturesFollow
                          ? 'redrawn from your decisions and circles.'
                          : 'redrawn only if every finding has a circle (the AI sent none for some of them: draw one for each below); otherwise it stays the AI\u2019s original.'}
                      </p>
                      {findings.length === 0 && (
                        <p className="text-sm text-muted-foreground">The AI recorded no findings. You can add some below.</p>
                      )}
                      {findings.map(([name, f]) => (
                        <fieldset key={name} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 first:border-t-0 first:pt-0">
                          <legend className="sr-only">{label(name)}</legend>
                          <span className="text-sm">
                            {label(name)} <span className="text-muted-foreground">· {pct(f.positive_prob ?? f.probability)}</span>
                          </span>
                          <span className="flex gap-3 text-sm">
                            {(['confirm', 'remove'] as const).map((d) => (
                              <label key={d} className="flex items-center gap-1.5">
                                <input
                                  type="radio"
                                  name={`decision-${name}`}
                                  checked={decisions[name] === d}
                                  onChange={() => setDecisions({ ...decisions, [name]: d })}
                                />
                                {d === 'confirm' ? 'Confirm' : 'Remove'}
                              </label>
                            ))}
                          </span>
                        </fieldset>
                      ))}

                      <div className="space-y-2 border-t pt-3">
                        <label htmlFor="add-finding" className="text-xs font-medium">Add a finding the AI missed</label>
                        <div className="flex gap-2">
                          <input
                            id="add-finding"
                            type="text"
                            value={addText}
                            maxLength={60}
                            placeholder="e.g. Cardiomegaly"
                            className="h-9 min-w-0 flex-1 rounded-lg border bg-background px-3 text-sm"
                            onChange={(e) => setAddText(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addFinding() } }}
                          />
                          <Button type="button" variant="outline" className="h-9" onClick={addFinding} disabled={!addText.trim()}>
                            <Plus className="size-4" /> Add
                          </Button>
                        </div>
                        {added.length > 0 && (
                          <ul className="flex flex-wrap gap-1.5">
                            {added.map((a) => (
                              <li key={a}>
                                <Badge>
                                  {a}
                                  <button
                                    type="button"
                                    aria-label={`Remove added finding ${a}`}
                                    className="ml-1.5 inline-flex"
                                    onClick={() => setAdded(added.filter((x) => x !== a))}
                                  >
                                    <X className="size-3" />
                                  </button>
                                </Badge>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>

                      <div className="space-y-2 border-t pt-3">
                        <p className="text-xs font-medium">Circles on the picture</p>
                        {!review.canvas_px || editableKeys.length === 0 ? (
                          <p className="text-xs text-muted-foreground">
                            {editableKeys.length === 0
                              ? 'Keep or add a finding to mark circles for it.'
                              : 'Circles cannot be edited for this visit (its X-ray could not be read).'}
                          </p>
                        ) : (
                          <div className="grid gap-4 md:grid-cols-[minmax(0,32rem)_1fr]">
                            <RegionEditor
                              imageUrl={images?.xray ?? null}
                              canvas={review.canvas_px}
                              items={editorItems}
                              selected={selected && editorItems.some((it) => it.key === selected.key) ? selected : null}
                              onSelect={setSelected}
                              onChange={(key, list) => setCircles({ ...circles, [key]: list })}
                            />
                            <div className="space-y-3 text-sm">
                              <fieldset className="space-y-1.5">
                                <legend className="text-xs text-muted-foreground">New circles go to:</legend>
                                {editorItems.map((it) => (
                                  <label key={it.key} className="flex items-center gap-2">
                                    <input
                                      type="radio"
                                      name="circle-target"
                                      checked={(activeKey && editorItems.some((x) => x.key === activeKey) ? activeKey : editorItems[0]?.key) === it.key}
                                      onChange={() => setActiveKey(it.key)}
                                    />
                                    <span className="inline-block size-3 rounded-full" style={{ background: it.color }} aria-hidden />
                                    <span>{it.label}</span>
                                    <span className="text-xs text-muted-foreground">
                                      ({it.circles.length}/{MAX_CIRCLES} circle{it.circles.length === 1 ? '' : 's'})
                                    </span>
                                  </label>
                                ))}
                              </fieldset>
                              <div className="flex flex-wrap gap-2">
                                <Button type="button" variant="outline" className="h-8" onClick={addCircle}>
                                  <Plus className="size-4" /> Add circle
                                </Button>
                                <Button type="button" variant="outline" className="h-8" onClick={deleteSelected} disabled={!selected}>
                                  <Trash2 className="size-4" /> Delete selected
                                </Button>
                                <Button type="button" variant="ghost" className="h-8" onClick={resetCircles}>
                                  Undo circle changes
                                </Button>
                              </div>
                              <p className="text-xs text-muted-foreground">
                                Drag a circle to move it. Select it, then drag the dot on its right edge to resize.
                                Keyboard: arrow keys move, + and - resize, Delete removes.
                                Circles show where a finding is; they are the doctor&apos;s marks, not a lesion outline.
                              </p>
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="space-y-1 border-t pt-3">
                        <label htmlFor="doctor-note" className="text-xs font-medium">Your note (goes into the report)</label>
                        <textarea
                          id="doctor-note"
                          value={note}
                          maxLength={MAX_NOTE}
                          rows={3}
                          className="w-full rounded-lg border bg-background px-3 py-2 text-sm"
                          onChange={(e) => setNote(e.target.value)}
                        />
                        <p className="text-right text-xs text-muted-foreground">{note.length}/{MAX_NOTE}</p>
                      </div>

                      {editError && (
                        <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                          {editError}
                        </p>
                      )}
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          className="h-9"
                          onClick={() => void saveEdit()}
                          disabled={saving || !(Object.values(decisions).some((d) => d === 'remove') || added.length > 0 || note.trim() !== '' || Object.keys(changedCircles).length > 0)}
                        >
                          {saving && <Loader2 className="size-4 animate-spin" />}
                          Save as new version
                        </Button>
                        <Button variant="ghost" className="h-9" onClick={cancelEdit} disabled={saving}>Cancel</Button>
                        <span className="text-xs text-muted-foreground">Nothing is saved until you press Save.</span>
                      </div>
                    </div>
                  )}
                  {!editing && (findings.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No findings recorded.</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-sm">
                        <thead className="text-xs text-muted-foreground">
                          <tr>
                            <th className="py-1.5 pr-4 font-medium">Disease</th>
                            <th className="py-1.5 pr-4 font-medium">Probability</th>
                            <th className="py-1.5 pr-4 font-medium">Method</th>
                            <th className="py-1.5 pr-4 font-medium">Regions</th>
                            <th className="py-1.5 pr-4 font-medium">Localized</th>
                            <th className="py-1.5 font-medium">Shown</th>
                          </tr>
                        </thead>
                        <tbody>
                          {findings.map(([name, f]) => (
                            <tr key={name} className="border-t">
                              <td className="py-1.5 pr-4">
                                {label(name)}
                                {(f as { doctor_status?: string }).doctor_status && (
                                  <span className="ml-2 text-xs text-muted-foreground">
                                    ({(f as { doctor_status?: string }).doctor_status} by doctor)
                                  </span>
                                )}
                              </td>
                              <td className="py-1.5 pr-4">{pct(f.positive_prob ?? f.probability)}</td>
                              <td className="py-1.5 pr-4">{f.method ?? '—'}</td>
                              <td className="py-1.5 pr-4">{f.region_count ?? '—'}</td>
                              <td className="py-1.5 pr-4">
                                {f.localized === true ? 'Yes' : f.localized === false ? 'No' : '—'}
                              </td>
                              <td className="py-1.5">{shown.has(name) ? 'Yes' : 'No'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                  {!editing && (s?.removed_findings?.length ?? 0) > 0 && (
                    <div className="space-y-1.5 pt-1">
                      <p className="text-xs text-muted-foreground">Removed by the reviewing doctor:</p>
                      <div className="flex flex-wrap gap-1.5">
                        {s?.removed_findings?.map((n) => (
                          <Badge key={n} variant="muted">{label(n)}</Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  {/* The AI's 'qualified but not drawn' list is only useful before a doctor has reviewed. */}
                  {notShown.length > 0 && review.report.source !== 'doctor_edit' && (
                    <div className="space-y-1.5 pt-1">
                      <p className="text-xs text-muted-foreground">
                        Qualified by probability but not drawn on the image:
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {notShown.map((n) => (
                          <Badge key={n.disease} variant="muted">
                            {label(n.disease)} · {pct(n.probability)}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardContent className="space-y-2 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium">Report</p>
                    <Badge variant="muted">
                      Version {review.report.version_no} ·{' '}
                      {review.report.source === 'ai' ? 'AI generated' : 'Doctor edited'}
                    </Badge>
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{review.report.report_text}</p>
                </CardContent>
              </Card>

              <Card>
                <CardContent className="space-y-2 p-4">
                  <p className="text-sm font-medium">Version history</p>
                  <ul className="space-y-1 text-sm">
                    {review.versions.map((v) => (
                      <li key={v.version_no} className="flex flex-wrap items-center gap-2">
                        <span>Version {v.version_no}</span>
                        <span className="text-muted-foreground">
                          {v.source === 'ai' ? 'AI' : `Doctor ${v.author ?? ''}`.trim()} · {when(v.created_at)}
                        </span>
                        {v.is_final && <Badge>Final</Badge>}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    )
  }

  // ── Records and visits ────────────────────────────────────────────────────
  return (
    <div>
      {header}
      {errorBox}

      {!openRecord && (
        <>
          {records === null && !error && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading records…
            </div>
          )}
          {records !== null && records.length === 0 && (
            <Card>
              <CardContent className="space-y-2 p-6">
                <p className="font-medium">Nothing to review yet</p>
                <p className="text-sm text-muted-foreground">
                  Analyses you run from Upload are saved here for review.
                </p>
              </CardContent>
            </Card>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            {records?.map((r) => (
              <Card key={r.patient_code}>
                <CardContent className="space-y-3 p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-semibold">{r.name || 'Record'}</p>
                      <p className="font-mono text-xs text-muted-foreground">{r.patient_code}</p>
                    </div>
                    <Badge variant="muted">
                      {r.visit_count} visit{r.visit_count === 1 ? '' : 's'}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">Last visit: {when(r.last_visit_at)}</p>
                  <Button className="h-9" onClick={() => chooseRecord(r)}>
                    <FolderOpen className="size-4" />
                    Open
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}

      {openRecord && (
        <div className="space-y-4">
          <Button variant="ghost" className="h-9 px-2" onClick={() => { setOpenRecord(null); setVisits(null) }}>
            <ArrowLeft className="size-4" />
            All records
          </Button>
          <div>
            <p className="font-semibold">{openRecord.name || 'Record'}</p>
            <p className="font-mono text-xs text-muted-foreground">{openRecord.patient_code}</p>
          </div>
          {visits === null && !error && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading visits…
            </div>
          )}
          <div className="space-y-3">
            {visits?.map((v) => (
              <Card key={v.session_id}>
                <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
                  <div className="min-w-0 space-y-1.5">
                    <p className="text-sm font-medium">{when(v.created_at)}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {v.has_report ? (
                        v.diseases_visualized.length > 0 ? (
                          v.diseases_visualized.map((d) => <Badge key={d}>{label(d)}</Badge>)
                        ) : (
                          <Badge variant="muted">No findings flagged</Badge>
                        )
                      ) : (
                        <Badge variant="muted">Questions only</Badge>
                      )}
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    className="h-9"
                    disabled={loadingVisit === v.session_id}
                    onClick={() => void openReview(v)}
                  >
                    {loadingVisit === v.session_id ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Stethoscope className="size-4" />
                    )}
                    Review
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
