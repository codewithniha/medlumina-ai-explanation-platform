'use client'

import { useEffect, useState } from 'react'
import { ArrowLeft, Download, FileText, FolderOpen, Loader2, MessagesSquare, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { PageHeader } from './page-header'
import { useToast } from '@/components/ui/toast'
import { useApp } from '@/lib/app-context'
import { downloadDicom, listRecords, listVisits, type RecordSummary, type VisitListItem } from '@/lib/api-client'
import { loadVisitForDisplay } from '@/lib/visit-loader'

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

// "My Records": everything this account has saved on the server. Read-only --
// this screen can open a visit, but nothing here (and no server route) edits one.
export function RecordsScreen() {
  const { setSession, navigate } = useApp()
  const { toast } = useToast()
  const [records, setRecords] = useState<RecordSummary[] | null>(null)
  const [openRecord, setOpenRecord] = useState<RecordSummary | null>(null)
  const [visits, setVisits] = useState<VisitListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [opening, setOpening] = useState<string | null>(null)

  useEffect(() => {
    listRecords()
      .then(setRecords)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load your records.'))
  }, [])

  function chooseRecord(r: RecordSummary) {
    setOpenRecord(r)
    setVisits(null)
    setError(null)
    listVisits(r.patient_code)
      .then(setVisits)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load this record.'))
  }

  async function saveDicom(v: VisitListItem, kind: 'original' | 'deidentified') {
    try {
      await downloadDicom(v.session_id, kind)
    } catch (e) {
      toast({
        title: kind === 'original' ? 'Could not download the DICOM file' : 'Could not export the de-identified copy',
        description: e instanceof Error ? e.message : 'Unknown error.',
      })
    }
  }

  async function openVisit(v: VisitListItem) {
    if (!openRecord) return
    setOpening(v.session_id)
    try {
      const loaded = await loadVisitForDisplay(v.session_id)
      setSession({
        sessionId: v.session_id,
        patientCode: openRecord.patient_code,
        inputMode: loaded.inputMode,
        analyzed: true,
        analysisResult: loaded.analysisResult,
        imagePreviewUrl: loaded.imagePreviewUrl,
        analysisError: null,
        hasImage: !!loaded.imagePreviewUrl,
      })
      navigate(loaded.analysisResult ? 'report' : 'qa')
    } catch (e) {
      toast({
        title: 'Could not open this visit',
        description: e instanceof Error ? e.message : 'Unknown error.',
      })
    } finally {
      setOpening(null)
    }
  }

  function newVisitInRecord(r: RecordSummary) {
    setSession({ patientCode: r.patient_code, sessionId: null, analyzed: false, analysisResult: null, imagePreviewUrl: null })
    toast({
      title: `New visit in ${r.name || r.patient_code}`,
      description: 'Upload as usual — it will be added to this record so visits can be compared over time.',
    })
    navigate('input')
  }

  return (
    <div>
      <PageHeader
        eyebrow="Your account"
        title="My Records"
        description="Every visit you saved, newest first. Opening a visit shows exactly what was saved — nothing here can be changed."
        showModeSwitcher={false}
      />

      {error && (
        <p role="alert" className="mb-4 rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      {!openRecord && (
        <>
          {records === null && !error && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading your records…
            </div>
          )}
          {records !== null && records.length === 0 && (
            <Card>
              <CardContent className="space-y-3 p-6">
                <p className="font-medium">No saved records yet</p>
                <p className="text-sm text-muted-foreground">
                  Upload an X-ray and run the analysis — it is saved to your account automatically.
                </p>
                <Button className="h-10" onClick={() => navigate('input')}>
                  Upload an X-ray
                </Button>
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
                  <div className="flex flex-wrap gap-2">
                    <Button className="h-9" onClick={() => chooseRecord(r)}>
                      <FolderOpen className="size-4" />
                      Open
                    </Button>
                    <Button variant="outline" className="h-9" onClick={() => newVisitInRecord(r)}>
                      <Plus className="size-4" />
                      New visit
                    </Button>
                  </div>
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
                          v.diseases_visualized.map((d) => (
                            <Badge key={d}>{label(d)}</Badge>
                          ))
                        ) : (
                          <Badge variant="muted">No findings flagged</Badge>
                        )
                      ) : (
                        <Badge variant="muted">Questions only — no saved report</Badge>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                  {v.has_dicom && (
                    <>
                      <Button variant="ghost" className="h-9" onClick={() => void saveDicom(v, 'original')}
                        title="The original DICOM file exactly as uploaded. It contains the details stored in the file.">
                        <Download className="size-4" />
                        Original DICOM
                      </Button>
                      <Button variant="ghost" className="h-9" onClick={() => void saveDicom(v, 'deidentified')}
                        title="A copy with names, IDs, dates and other personal details removed, safe to share.">
                        <Download className="size-4" />
                        De-identified copy
                      </Button>
                    </>
                  )}
                  <Button
                    variant="outline"
                    className="h-9"
                    disabled={opening === v.session_id}
                    onClick={() => void openVisit(v)}
                  >
                    {opening === v.session_id ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : v.has_report ? (
                      <FileText className="size-4" />
                    ) : (
                      <MessagesSquare className="size-4" />
                    )}
                    {v.has_report ? 'Open report' : 'Open chat'}
                  </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
