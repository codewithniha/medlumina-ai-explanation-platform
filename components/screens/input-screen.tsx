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
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { PageHeader } from './page-header'
import { useApp, type InputMode } from '@/lib/app-context'
import { runAnalysis } from '@/lib/api-client'
import { cn } from '@/lib/utils'

type UploadPhase = 'idle' | 'uploading' | 'ready'

function SectionLabel({
  icon: Icon,
  title,
  optional,
  required,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  optional?: boolean
  required?: boolean
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
      {required && (
        <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary">
          Required
        </span>
      )}
    </div>
  )
}

const xrayProcessingSteps = [
  'Validating X-ray image',
  'Detecting key regions',
  'Analyzing opacity patterns',
  'Writing plain-language report',
]

const prescriptionProcessingSteps = [
  'Reading prescribed medicines',
  'Identifying drug classes',
  'Matching medicine purposes',
  'Inferring likely condition',
]

const modeOptions: {
  id: InputMode
  title: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}[] = [
  {
    id: 'xray_report',
    title: 'X-ray + Doctor\u2019s Report',
    description: 'Explain the findings from your existing report.',
    icon: FileText,
  },
  {
    id: 'xray_only',
    title: 'X-ray Only',
    description: 'Generate a preliminary report from the image.',
    icon: ScanLine,
  },
  {
    id: 'prescription_only',
    title: 'Prescription / Medicines Only',
    description: 'Understand your medicines and likely condition.',
    icon: Pill,
  },
]

function ProcessingChecklist({
  steps,
  step,
}: {
  steps: string[]
  step: number
}) {
  return (
    <div className="w-full max-w-[240px] space-y-2">
      {steps.map((s, i) => (
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
  )
}

function AnalyzingOverlay({ steps, step }: { steps: string[]; step: number }) {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 rounded-2xl bg-background/85 backdrop-blur-sm">
      <div className="relative flex size-16 items-center justify-center rounded-full border border-primary/30">
        <span className="absolute inset-0 animate-ping rounded-full bg-primary/20" />
        <ScanLine className="size-7 text-primary" />
      </div>
      <ProcessingChecklist steps={steps} step={step} />
    </div>
  )
}

function AnalyzingCard({ steps, step }: { steps: string[]; step: number }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 px-6 py-14">
        <div className="relative flex size-16 items-center justify-center rounded-full border border-primary/30">
          <span className="absolute inset-0 animate-ping rounded-full bg-primary/20" />
          <Pill className="size-7 text-primary" />
        </div>
        <p className="text-sm font-semibold text-foreground">
          Analyzing your prescription
        </p>
        <ProcessingChecklist steps={steps} step={step} />
      </CardContent>
    </Card>
  )
}

export function InputScreen() {
  const { navigate, setSession, session, setInputMode } = useApp()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const mode = session.inputMode
  const isPrescription = mode === 'prescription_only'

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
  const [xrayOptionalOpen, setXrayOptionalOpen] = useState(false)
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const hasImage = phase === 'ready'
  const hasReport = reportText.trim().length > 0
  const processingSteps = isPrescription
    ? prescriptionProcessingSteps
    : xrayProcessingSteps
  // Mode A needs both the image and the doctor's report; Mode B needs the
  // image; Mode C needs at least one medicine.
  const canAnalyze = isPrescription
    ? medicines.length > 0
    : mode === 'xray_report'
      ? hasImage && hasReport
      : hasImage

  // Mode-specific helper text shown under the disabled Analyze button.
  const helperText = isPrescription
    ? 'Add at least one prescribed medicine to enable analysis.'
    : mode === 'xray_report'
      ? !hasImage
        ? 'Add an X-ray image to enable analysis.'
        : 'Add your doctor\u2019s report to enable analysis.'
      : 'Add an X-ray image to enable analysis.'

  // Takes the real File the patient picked or dropped, previews it locally,
  // and plays a short progress animation before revealing it (the actual
  // upload to the backend only happens later, when Analyze is clicked).
  function handleFile(file: File) {
    if (phase !== 'idle') return
    if (!file.type.startsWith('image/')) return
    setImageFile(file)
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return URL.createObjectURL(file)
    })
    setPhase('uploading')
    setProgress(0)
  }

  function removeImage() {
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return null
    })
    setImageFile(null)
    setPhase('idle')
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
  }, [analyzing, processingSteps.length])

  function addMedicine() {
    const value = medInput.trim()
    if (value && !medicines.includes(value)) {
      setMedicines((prev) => [...prev, value])
    }
    setMedInput('')
  }

  async function analyze() {
    setAnalyzing(true)
    setAnalyzeStep(0)
    setErrorMessage(null)
    setSession({ reportText, symptoms, medicines, hasImage })

    // Prescription-only has no backend wired up yet — Module 2/5 only handle
    // X-ray images, and the medicine/condition-inference module (3/6) wasn't
    // part of what was uploaded, so this mode stays on demo data for now.
    if (isPrescription) {
      setTimeout(() => {
        setAnalyzing(false)
        setSession({ analyzed: true })
        navigate('report')
      }, 2400)
      return
    }

    if (!imageFile) {
      setAnalyzing(false)
      return
    }

    try {
      const result = await runAnalysis({
        image: imageFile,
        reportText: mode === 'xray_report' ? reportText : undefined,
      })
      setSession({
        analyzed: true,
        analysisResult: result,
        analysisError: null,
        imagePreviewUrl: previewUrl,
      })
      setAnalyzing(false)
      navigate('report')
    } catch (err) {
      setAnalyzing(false)
      const message = err instanceof Error ? err.message : 'Analysis failed. Please try again.'
      setErrorMessage(message)
      setSession({ analysisError: message })
    }
  }

  // The X-ray upload / preview block, reused for modes A & B and as the
  // optional add-on in mode C.
  const xrayUploader = (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg"
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) handleFile(file)
          e.target.value = ''
        }}
      />

      {phase === 'idle' && (
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files?.[0]
            if (file) handleFile(file)
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
            Uploading {imageFile?.name ?? 'image'}
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
            {analyzing && !isPrescription && (
              <AnalyzingOverlay steps={processingSteps} step={analyzeStep} />
            )}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={previewUrl ?? '/chest-xray.png'}
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
                {imageFile?.name ?? 'chest-xray.png'}
              </p>
              <p className="text-xs text-muted-foreground">
                {imageFile ? `${(imageFile.size / (1024 * 1024)).toFixed(1)} MB · Ready` : 'Ready'}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={removeImage}
              disabled={analyzing}
              aria-label="Remove image"
            >
              <X className="size-4" />
            </Button>
          </CardContent>
        </Card>
      )}
    </>
  )

  // The medicine tag input, used as a promoted primary field in mode C and as
  // an optional field in modes A & B.
  const medicinesField = (
    <div>
      <SectionLabel
        icon={Pill}
        title="Prescribed Medicines"
        optional={!isPrescription}
        required={isPrescription}
      />
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
  )

  const symptomsField = (
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
  )

  const activeOption = modeOptions.find((o) => o.id === mode)

  return (
    <div>
      <PageHeader
        eyebrow="Step 1"
        title={isPrescription ? 'Upload your prescription' : 'Upload your X-ray'}
        description={
          isPrescription
            ? 'Add the medicines you were prescribed and we\u2019ll explain what each one does and the likely condition behind them. Symptoms are optional.'
            : 'Choose how you want MedLumina to help, then add your details. We\u2019ll explain whatever you provide.'
        }
        showModeSwitcher={false}
      />

      {/* Input mode selector */}
      <div className="mb-8">
        <p className="mb-3 text-sm font-semibold text-foreground">
          What do you have to explain?
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {modeOptions.map((opt) => {
            const Icon = opt.icon
            const active = mode === opt.id
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => setInputMode(opt.id)}
                aria-pressed={active}
                className={cn(
                  'flex flex-col items-start gap-2 rounded-2xl border-2 p-4 text-left transition-all duration-200',
                  active
                    ? 'border-primary bg-primary/5 shadow-[0_4px_16px_-8px_var(--color-primary)]'
                    : 'border-border bg-card hover:border-primary/40 hover:bg-accent/30',
                )}
              >
                <span
                  className={cn(
                    'flex size-10 items-center justify-center rounded-xl',
                    active
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-primary/10 text-primary',
                  )}
                >
                  <Icon className="size-5" />
                </span>
                <span className="text-sm font-semibold text-foreground">
                  {opt.title}
                </span>
                <span className="text-xs leading-relaxed text-muted-foreground">
                  {opt.description}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left / primary column */}
        <div className="lg:col-span-5">
          <div className="space-y-6 lg:sticky lg:top-8">
            {isPrescription ? (
              analyzing ? (
                <AnalyzingCard steps={processingSteps} step={analyzeStep} />
              ) : (
                <>
                  {medicinesField}

                  {/* Optional X-ray add-on for patients who also have one. */}
                  <div className="rounded-2xl border border-border bg-card/60 p-4">
                    <button
                      type="button"
                      onClick={() => setXrayOptionalOpen((v) => !v)}
                      className="flex w-full items-center justify-between gap-2 text-left"
                    >
                      <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                        <ImageIcon className="size-4 text-primary" />
                        Have an X-ray too? Add it
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                          Optional
                        </span>
                      </span>
                      {xrayOptionalOpen ? (
                        <ChevronUp className="size-4 text-muted-foreground" />
                      ) : (
                        <ChevronDown className="size-4 text-muted-foreground" />
                      )}
                    </button>
                    {xrayOptionalOpen && (
                      <div className="mt-4">{xrayUploader}</div>
                    )}
                  </div>
                </>
              )
            ) : (
              <>
                <SectionLabel icon={ImageIcon} title="X-ray Image" required />
                {xrayUploader}
              </>
            )}
          </div>
        </div>

        {/* Right / details column */}
        <div className="space-y-6 lg:col-span-7">
          {mode === 'xray_report' && (
            <div>
              <SectionLabel icon={FileText} title="Doctor's Report" required />
              <Textarea
                value={reportText}
                onChange={(e) => setReportText(e.target.value)}
                placeholder="Paste or type the text from your radiology report here..."
                className="min-h-32"
              />
              <p className="mt-1.5 text-xs text-muted-foreground">
                We&apos;ll translate your doctor&apos;s findings into plain
                language rather than diagnosing from scratch.
              </p>
            </div>
          )}

          {mode === 'xray_only' && (
            <div className="flex items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/5 p-4">
              <ScanLine className="mt-0.5 size-4 shrink-0 text-amber-400" />
              <p className="text-xs leading-relaxed text-muted-foreground">
                No doctor&apos;s report needed for this mode — MedLumina will
                generate a preliminary report from the image alone. It must be
                confirmed by a doctor.
              </p>
            </div>
          )}

          {/* Medicines are optional here for A/B; in C they live in the primary
              column above. */}
          {!isPrescription && medicinesField}

          {symptomsField}

          <div className="sticky bottom-20 lg:bottom-6">
            {errorMessage && (
              <div className="mb-3 rounded-xl border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-400">
                {errorMessage}
              </div>
            )}
            <Button
              className="h-13 w-full py-3.5 text-base shadow-[0_8px_30px_-8px_var(--color-primary)]"
              disabled={!canAnalyze || analyzing}
              onClick={analyze}
            >
              {analyzing ? (
                <>
                  <Loader2 className="size-5 animate-spin" />
                  {isPrescription
                    ? 'Analyzing your prescription...'
                    : 'Analyzing your X-ray...'}
                </>
              ) : (
                <>
                  <Sparkles className="size-5" />
                  {isPrescription ? 'Analyze Prescription' : 'Analyze X-ray'}
                </>
              )}
            </Button>
            {!canAnalyze && (
              <p className="mt-2 text-center text-xs text-muted-foreground">
                {isPrescription
                  ? 'Add at least one prescribed medicine to enable analysis.'
                  : 'Add an X-ray image to enable analysis.'}
              </p>
            )}
          </div>
        </div>
      </div>

      {activeOption && (
        <p className="sr-only">Selected input mode: {activeOption.title}</p>
      )}
    </div>
  )
}
