'use client'

import { useRef, useState, useEffect } from 'react'
import {
  UploadCloud,
  FileText,
  Pill,
  Stethoscope,
  X,
  Plus,
  ImageIcon,
  Loader2,
  Sparkles,
  CheckCircle2,
  ScanLine,
  ShieldCheck,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { PageHeader } from './page-header'
import { useApp } from '@/lib/app-context'
import { cn } from '@/lib/utils'

type UploadPhase = 'idle' | 'uploading' | 'ready'

function SectionLabel({
  icon: Icon,
  title,
  optional,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  optional?: boolean
}) {
  return (
    <div className="mb-2.5 flex items-center gap-2">
      <Icon className="size-4 text-primary" />
      <label className="text-sm font-semibold text-foreground">{title}</label>
      {optional && (
        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
          Optional
        </span>
      )}
    </div>
  )
}

const processingSteps = [
  'Validating X-ray image',
  'Detecting key regions',
  'Analyzing opacity patterns',
  'Writing plain-language report',
]

function AnalyzingOverlay({ step }: { step: number }) {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 rounded-2xl bg-background/85 backdrop-blur-sm">
      <div className="relative flex size-16 items-center justify-center rounded-full border border-primary/30">
        <span className="absolute inset-0 animate-ping rounded-full bg-primary/20" />
        <ScanLine className="size-7 text-primary" />
      </div>
      <div className="w-full max-w-[220px] space-y-2">
        {processingSteps.map((s, i) => (
          <div key={s} className="flex items-center gap-2 text-xs">
            {i < step ? (
              <CheckCircle2 className="size-4 shrink-0 text-primary" />
            ) : i === step ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-primary" />
            ) : (
              <span className="size-4 shrink-0 rounded-full border border-border" />
            )}
            <span
              className={cn(
                'font-medium',
                i <= step ? 'text-foreground' : 'text-muted-foreground',
              )}
            >
              {s}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function InputScreen() {
  const { navigate, setSession } = useApp()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [phase, setPhase] = useState<UploadPhase>('idle')
  const [progress, setProgress] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [reportText, setReportText] = useState('')
  const [symptoms, setSymptoms] = useState('')
  const [medicines, setMedicines] = useState<string[]>([
    'Amoxicillin 500mg',
    'Paracetamol 500mg',
  ])
  const [medInput, setMedInput] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeStep, setAnalyzeStep] = useState(0)

  const hasImage = phase === 'ready'

  // Simulate an upload with a progress bar, then reveal the preview.
  function startUpload() {
    if (phase !== 'idle') return
    setPhase('uploading')
    setProgress(0)
  }

  useEffect(() => {
    if (phase !== 'uploading') return
    const timer = setInterval(() => {
      setProgress((p) => {
        if (p >= 100) {
          clearInterval(timer)
          setPhase('ready')
          return 100
        }
        return p + 8
      })
    }, 60)
    return () => clearInterval(timer)
  }, [phase])

  // Advance the fake processing checklist while analyzing.
  useEffect(() => {
    if (!analyzing) return
    const timer = setInterval(() => {
      setAnalyzeStep((s) => Math.min(s + 1, processingSteps.length - 1))
    }, 550)
    return () => clearInterval(timer)
  }, [analyzing])

  function addMedicine() {
    const value = medInput.trim()
    if (value && !medicines.includes(value)) {
      setMedicines((prev) => [...prev, value])
    }
    setMedInput('')
  }

  function analyze() {
    setAnalyzing(true)
    setAnalyzeStep(0)
    setSession({
      reportText,
      symptoms,
      medicines,
      hasImage: true,
      analyzed: true,
    })
    setTimeout(() => {
      setAnalyzing(false)
      navigate('report')
    }, 2400)
  }

  return (
    <div>
      <PageHeader
        eyebrow="Step 1 of 6"
        title="Upload your X-ray"
        description="Add your chest X-ray image and any report or details you have. Everything except the image is optional — we'll explain whatever you provide."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left: upload + preview */}
        <div className="lg:col-span-5">
          <div className="lg:sticky lg:top-8">
            <SectionLabel icon={ImageIcon} title="X-ray Image" />
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg"
              className="sr-only"
              onChange={startUpload}
            />

            {phase === 'idle' && (
              <button
                type="button"
                onClick={startUpload}
                onDragOver={(e) => {
                  e.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragging(false)
                  startUpload()
                }}
                className={cn(
                  'group flex w-full flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-16 text-center transition-all duration-300',
                  dragging
                    ? 'scale-[1.02] border-primary bg-primary/10'
                    : 'border-border bg-card hover:border-primary/50 hover:bg-accent/30',
                )}
              >
                <div
                  className={cn(
                    'flex size-16 items-center justify-center rounded-2xl bg-primary/10 text-primary transition-transform duration-300',
                    dragging ? 'scale-110' : 'group-hover:scale-105',
                  )}
                >
                  <UploadCloud className="size-8" />
                </div>
                <p className="mt-5 text-base font-semibold text-foreground">
                  {dragging ? 'Drop to upload' : 'Drag & drop your X-ray here'}
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  or click to browse — PNG or JPG, up to 20MB
                </p>
                <span className="mt-4 inline-flex items-center gap-1.5 rounded-full border border-border bg-background/50 px-3 py-1 text-xs font-medium text-muted-foreground">
                  <ShieldCheck className="size-3.5 text-primary" />
                  Processed privately for this demo
                </span>
              </button>
            )}

            {phase === 'uploading' && (
              <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-primary/40 bg-card px-6 py-16">
                <div className="flex size-16 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                  <Loader2 className="size-8 animate-spin" />
                </div>
                <p className="mt-5 text-sm font-semibold text-foreground">
                  Uploading chest-xray.png
                </p>
                <div className="mt-3 h-2 w-full max-w-xs overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-all duration-100"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <p className="mt-2 text-xs font-medium text-muted-foreground">
                  {progress}%
                </p>
              </div>
            )}

            {phase === 'ready' && (
              <Card className="overflow-hidden">
                <div className="relative aspect-square w-full bg-neutral-950">
                  {analyzing && <AnalyzingOverlay step={analyzeStep} />}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src="/chest-xray.png"
                    alt="Uploaded chest X-ray preview"
                    className="size-full object-cover"
                  />
                  {!analyzing && (
                    <Badge
                      variant="success"
                      className="absolute left-3 top-3 bg-emerald-500/90 text-white"
                    >
                      <CheckCircle2 className="size-3.5" />
                      Ready
                    </Badge>
                  )}
                </div>
                <CardContent className="flex items-center gap-3 p-4">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-foreground">
                      chest-xray.png
                    </p>
                    <p className="text-xs text-muted-foreground">
                      2.4 MB · Uploaded successfully
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      setPhase('idle')
                      setProgress(0)
                    }}
                    disabled={analyzing}
                    aria-label="Remove image"
                  >
                    <X className="size-4" />
                  </Button>
                </CardContent>
              </Card>
            )}
          </div>
        </div>

        {/* Right: details */}
        <div className="space-y-6 lg:col-span-7">
          <div>
            <SectionLabel icon={FileText} title="Doctor's Report" optional />
            <Textarea
              value={reportText}
              onChange={(e) => setReportText(e.target.value)}
              placeholder="Paste or type the text from your radiology report here..."
              className="min-h-32"
            />
          </div>

          <div>
            <SectionLabel icon={Pill} title="Prescribed Medicines" optional />
            <div className="flex gap-2">
              <Input
                value={medInput}
                onChange={(e) => setMedInput(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    e.key === 'Enter' &&
                    !e.nativeEvent.isComposing &&
                    e.keyCode !== 229
                  ) {
                    e.preventDefault()
                    addMedicine()
                  }
                }}
                placeholder="e.g. Amoxicillin 500mg"
              />
              <Button
                type="button"
                variant="secondary"
                className="h-11 shrink-0 px-4"
                onClick={addMedicine}
              >
                <Plus className="size-4" />
                Add
              </Button>
            </div>
            {medicines.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {medicines.map((med) => (
                  <Badge
                    key={med}
                    variant="secondary"
                    className="gap-1.5 py-1.5 pr-1.5 pl-3"
                  >
                    {med}
                    <button
                      type="button"
                      onClick={() =>
                        setMedicines((prev) => prev.filter((m) => m !== med))
                      }
                      className="flex size-4 items-center justify-center rounded-full transition-colors hover:bg-foreground/10"
                      aria-label={`Remove ${med}`}
                    >
                      <X className="size-3" />
                    </button>
                  </Badge>
                ))}
              </div>
            )}
          </div>

          <div>
            <SectionLabel
              icon={Stethoscope}
              title="Symptoms You're Experiencing"
              optional
            />
            <Textarea
              value={symptoms}
              onChange={(e) => setSymptoms(e.target.value)}
              placeholder="e.g. persistent cough, mild fever, tightness in chest..."
              className="min-h-24"
            />
          </div>

          <div className="sticky bottom-20 lg:bottom-6">
            <Button
              className="h-13 w-full py-3.5 text-base shadow-[0_8px_30px_-8px_var(--color-primary)]"
              disabled={!hasImage || analyzing}
              onClick={analyze}
            >
              {analyzing ? (
                <>
                  <Loader2 className="size-5 animate-spin" />
                  Analyzing your X-ray...
                </>
              ) : (
                <>
                  <Sparkles className="size-5" />
                  Analyze X-ray
                </>
              )}
            </Button>
            {!hasImage && (
              <p className="mt-2 text-center text-xs text-muted-foreground">
                Add an X-ray image to enable analysis.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
