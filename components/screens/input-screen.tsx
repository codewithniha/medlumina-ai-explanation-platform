'use client'

import { useRef, useState } from 'react'
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
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { PageHeader } from './page-header'
import { useApp } from '@/lib/app-context'

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
    <div className="mb-2 flex items-center gap-2">
      <Icon className="size-4 text-primary" />
      <label className="text-sm font-semibold text-foreground">{title}</label>
      {optional && (
        <span className="text-xs font-medium text-muted-foreground">
          Optional
        </span>
      )}
    </div>
  )
}

export function InputScreen() {
  const { navigate, setSession } = useApp()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [hasImage, setHasImage] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [reportText, setReportText] = useState('')
  const [symptoms, setSymptoms] = useState('')
  const [medicines, setMedicines] = useState<string[]>([
    'Amoxicillin 500mg',
    'Paracetamol 500mg',
  ])
  const [medInput, setMedInput] = useState('')
  const [analyzing, setAnalyzing] = useState(false)

  function addMedicine() {
    const value = medInput.trim()
    if (value && !medicines.includes(value)) {
      setMedicines((prev) => [...prev, value])
    }
    setMedInput('')
  }

  function analyze() {
    setAnalyzing(true)
    setSession({
      reportText,
      symptoms,
      medicines,
      hasImage: true,
      analyzed: true,
    })
    // Fake ~2s processing delay before navigating to the report.
    setTimeout(() => {
      setAnalyzing(false)
      navigate('report')
    }, 2000)
  }

  return (
    <div>
      <PageHeader
        eyebrow="Step 1 of 3"
        title="Upload your X-ray"
        description="Add your X-ray image and any report or details you have. Everything except the image is optional — we'll explain whatever you provide."
      />

      <div className="space-y-6">
        {/* Upload zone */}
        <div>
          <SectionLabel icon={ImageIcon} title="X-ray Image" />
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg"
            className="sr-only"
            onChange={() => setHasImage(true)}
          />
          {!hasImage ? (
            <button
              type="button"
              onClick={() => setHasImage(true)}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                setHasImage(true)
              }}
              className={`flex w-full flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
                dragging
                  ? 'border-primary bg-primary/5'
                  : 'border-border bg-card hover:border-primary/50 hover:bg-accent/40'
              }`}
            >
              <div className="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <UploadCloud className="size-7" />
              </div>
              <p className="mt-4 text-base font-semibold text-foreground">
                Drag & drop your X-ray here
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                or click to browse — PNG or JPG
              </p>
            </button>
          ) : (
            <Card>
              <CardContent className="flex items-center gap-4 p-4">
                <div className="relative size-20 shrink-0 overflow-hidden rounded-xl bg-neutral-900">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src="/chest-xray.png"
                    alt="Uploaded chest X-ray preview"
                    className="size-full object-cover"
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-foreground">
                    chest-xray.png
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Uploaded · Ready to analyze
                  </p>
                  <Badge variant="success" className="mt-2">
                    Image attached
                  </Badge>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setHasImage(false)}
                  aria-label="Remove image"
                >
                  <X className="size-4" />
                </Button>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Report text */}
        <div>
          <SectionLabel icon={FileText} title="Doctor's Report" optional />
          <Textarea
            value={reportText}
            onChange={(e) => setReportText(e.target.value)}
            placeholder="Paste or type the text from your radiology report here..."
            className="min-h-28"
          />
        </div>

        {/* Medicines */}
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

        {/* Symptoms */}
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
          />
        </div>

        {/* Analyze */}
        <div className="sticky bottom-20 lg:bottom-6">
          <Button
            className="h-13 w-full py-3.5 text-base"
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
                Analyze
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
  )
}
