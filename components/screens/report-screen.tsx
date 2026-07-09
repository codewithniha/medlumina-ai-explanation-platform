'use client'

import { useState } from 'react'
import {
  ScanEye,
  Lightbulb,
  Stethoscope,
  ClipboardList,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  ChevronDown,
  Activity,
  Gauge,
  ShieldCheck,
  ShieldAlert,
  Pill,
  Sparkles,
  FileCheck2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ConfidenceRing } from '@/components/confidence-ring'
import { PageHeader } from './page-header'
import { MedicineCard } from './medicine-screen'
import { useApp } from '@/lib/app-context'
import {
  mockReport,
  reportTimeline,
  mockMedicines,
  mockInferredCondition,
} from '@/lib/mock-data'
import { cn } from '@/lib/utils'

function StatCard({
  icon: Icon,
  label,
  value,
  tone = 'default',
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
  tone?: 'default' | 'warning' | 'success'
}) {
  const toneClasses = {
    default: 'bg-primary/10 text-primary',
    warning: 'bg-amber-500/15 text-amber-400',
    success: 'bg-emerald-500/15 text-emerald-400',
  }[tone]
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div
          className={cn(
            'flex size-10 shrink-0 items-center justify-center rounded-xl',
            toneClasses,
          )}
        >
          <Icon className="size-5" />
        </div>
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </p>
          <p className="truncate text-sm font-bold text-foreground">{value}</p>
        </div>
      </CardContent>
    </Card>
  )
}

function FindingRow({
  region,
  detail,
  status,
  tags,
  defaultOpen,
}: {
  region: string
  detail: string
  status: 'attention' | 'normal'
  tags: string[]
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(!!defaultOpen)
  const attention = status === 'attention'
  return (
    <div
      className={cn(
        'overflow-hidden rounded-xl border transition-colors',
        attention
          ? 'border-amber-500/30 bg-amber-500/5'
          : 'border-border bg-secondary/30',
      )}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3.5 text-left"
      >
        {attention ? (
          <AlertTriangle className="size-5 shrink-0 text-amber-400" />
        ) : (
          <CheckCircle2 className="size-5 shrink-0 text-primary" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground">{region}</p>
        </div>
        <Badge variant={attention ? 'warning' : 'success'}>
          {attention ? 'Needs attention' : 'Normal'}
        </Badge>
        <ChevronDown
          className={cn(
            'size-4 shrink-0 text-muted-foreground transition-transform duration-300',
            open && 'rotate-180',
          )}
        />
      </button>
      <div
        className={cn(
          'grid transition-all duration-300 ease-out',
          open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="px-4 pb-4 pl-12">
            <p className="text-sm leading-relaxed text-muted-foreground">
              {detail}
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {tags.map((t) => (
                <span
                  key={t}
                  className="rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
                >
                  {t}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// Mode C: Medicine & Condition Insight — no image, so medicines are the primary
// analysis and the likely condition is inferred from them.
function PrescriptionInsight() {
  const { navigate, stepEyebrow } = useApp()
  const inferred = mockInferredCondition

  return (
    <div>
      <PageHeader
        eyebrow={stepEyebrow('report')}
        title="Medicine & Condition Insight"
        description="Here is what each prescribed medicine is for, and the most likely condition suggested by the combination."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Medicines */}
        <div className="space-y-4 lg:col-span-7">
          <div className="flex items-center gap-2">
            <Pill className="size-5 text-primary" />
            <h2 className="text-base font-bold text-foreground">
              Your prescribed medicines
            </h2>
            <Badge variant="secondary" className="ml-1">
              {mockMedicines.length}
            </Badge>
          </div>
          {mockMedicines.map((medicine) => (
            <MedicineCard key={medicine.name} medicine={medicine} />
          ))}
        </div>

        {/* Inferred condition */}
        <div className="space-y-4 lg:col-span-5">
          <Card className="overflow-hidden border-primary/25">
            <div className="bg-gradient-to-br from-primary/10 via-card to-card">
              <CardContent className="p-6">
                <div className="flex items-center gap-2">
                  <Sparkles className="size-5 text-primary" />
                  <h3 className="text-base font-bold text-foreground">
                    Possible condition based on your medicines
                  </h3>
                </div>
                <div className="mt-4 flex items-center gap-4">
                  <ConfidenceRing value={inferred.confidence} />
                  <div>
                    <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      Inference confidence
                    </p>
                    <p className="text-sm font-semibold text-foreground">
                      {inferred.confidence}% likely
                    </p>
                  </div>
                </div>
                <p className="mt-4 text-lg font-bold text-foreground text-balance">
                  {inferred.condition}
                </p>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {inferred.reasoning}
                </p>
                <ul className="mt-4 space-y-2">
                  {inferred.signals.map((sig) => (
                    <li
                      key={sig}
                      className="flex items-start gap-2 text-sm text-foreground/90"
                    >
                      <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                      {sig}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </div>
          </Card>

          <Card className="border-amber-500/25 bg-amber-500/5">
            <CardContent className="flex gap-3 p-5">
              <ShieldAlert className="mt-0.5 size-5 shrink-0 text-amber-400" />
              <div>
                <p className="text-sm font-semibold text-foreground">
                  This is not a diagnosis
                </p>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  This possible condition is inferred only from what your
                  medicines are typically used for — no X-ray or scan was
                  reviewed. It must be confirmed by a doctor before you act on
                  it.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="mt-8 flex flex-col gap-3 sm:flex-row">
        <Button className="h-12 px-6 text-base" onClick={() => navigate('qa')}>
          <Sparkles className="size-4" />
          Ask a Question
          <ArrowRight className="size-4" />
        </Button>
        <Button
          variant="outline"
          className="h-12 px-6 text-base"
          onClick={() => navigate('summary')}
        >
          View full summary
        </Button>
      </div>
    </div>
  )
}

export function ReportScreen() {
  const { navigate, session, stepEyebrow } = useApp()
  const mode = session.inputMode

  if (mode === 'prescription_only') {
    return <PrescriptionInsight />
  }

  const report = mockReport
  const isReportMode = mode === 'xray_report'

  return (
    <div>
      <PageHeader
        eyebrow={stepEyebrow('report')}
        title={isReportMode ? 'Your Report, Explained' : 'Your AI-Generated Report'}
        description={
          isReportMode
            ? 'Your doctor\u2019s findings, confirmed against the image and translated into plain language.'
            : 'A preliminary reading generated from your X-ray image, followed by a plain-language summary of what it means for you.'
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Main column */}
        <div className="space-y-6 lg:col-span-8">
          {/* Hero summary */}
          <Card className="overflow-hidden">
            <div className="bg-gradient-to-br from-primary/10 via-card to-card">
              <CardContent className="flex flex-col items-center gap-6 p-6 sm:flex-row sm:items-center">
                <ConfidenceRing value={report.confidence} />
                <div className="flex-1 text-center sm:text-left">
                  <div className="flex flex-wrap justify-center gap-2 sm:justify-start">
                    <Badge variant="warning">
                      <Stethoscope className="size-3.5" />
                      {report.severity} finding
                    </Badge>
                    <Badge variant="secondary">
                      {isReportMode ? 'From your report' : 'Chest X-ray · PA view'}
                    </Badge>
                  </div>
                  <h2 className="mt-3 text-xl font-bold text-foreground text-balance">
                    {report.diagnosis}
                  </h2>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {isReportMode
                      ? `This ${report.confidence}% is the match confidence between the image and your doctor\u2019s report — the diagnosis comes from your doctor, not the model.`
                      : `The AI is ${report.confidence}% confident in this reading. A confidence score reflects how clearly the pattern appears — it is not a diagnosis and should be confirmed by your doctor.`}
                  </p>
                </div>
              </CardContent>
            </div>
          </Card>

          {/* Mode B: strengthened disclaimer that this is model-generated. */}
          {!isReportMode && (
            <Card className="border-amber-500/25 bg-amber-500/5">
              <CardContent className="flex gap-3 p-5">
                <ShieldAlert className="mt-0.5 size-5 shrink-0 text-amber-400" />
                <div>
                  <p className="text-sm font-semibold text-foreground">
                    Model-generated from the image alone
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    No physician report was provided, so this entire report was
                    generated by the model from your X-ray image only. It is a
                    preliminary explanation, not a diagnosis, and must be
                    reviewed and confirmed by a qualified doctor.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Mode A: confirmation that findings come from the doctor's report. */}
          {isReportMode && (
            <Card className="border-primary/25 bg-primary/5">
              <CardContent className="flex gap-3 p-5">
                <FileCheck2 className="mt-0.5 size-5 shrink-0 text-primary" />
                <div>
                  <p className="text-sm font-semibold text-foreground">
                    Confirmed from your doctor&apos;s report
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    The findings below are taken from the report you provided
                    and matched to the image — we&apos;ve simply rewritten them
                    in plain language, not re-diagnosed from scratch.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Findings */}
          <div>
            <div className="mb-3 flex items-center gap-2">
              <ClipboardList className="size-5 text-primary" />
              <h3 className="text-base font-bold text-foreground">Findings</h3>
              <span className="text-sm text-muted-foreground">
                ({report.findings.length})
              </span>
            </div>
            <div className="space-y-2.5">
              {report.findings.map((f, i) => (
                <FindingRow
                  key={f.region}
                  region={f.region}
                  detail={f.detail}
                  status={f.status}
                  tags={f.tags}
                  defaultOpen={i === 0}
                />
              ))}
            </div>
          </div>

          {/* Impression */}
          <Card>
            <CardContent className="p-5">
              <div className="mb-2 flex items-center gap-2">
                <Stethoscope className="size-5 text-primary" />
                <h3 className="text-base font-bold text-foreground">
                  Clinical impression
                </h3>
              </div>
              <p className="text-[15px] leading-relaxed text-foreground/90">
                {report.impression}
              </p>
            </CardContent>
          </Card>

          {/* Plain summary */}
          <Card className="border-primary/25 bg-primary/5">
            <CardContent className="p-5">
              <div className="mb-2 flex items-center gap-2">
                <Lightbulb className="size-5 text-primary" />
                <h3 className="text-base font-bold text-foreground">
                  What this means for you
                </h3>
              </div>
              <p className="text-base leading-relaxed text-foreground/90 text-pretty">
                {report.plainSummary}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Sidebar column */}
        <div className="space-y-4 lg:col-span-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-1">
            <StatCard
              icon={Gauge}
              label={isReportMode ? 'Match confidence' : 'Confidence'}
              value={`${report.confidence}% high`}
            />
            <StatCard
              icon={Activity}
              label="Severity"
              value={report.severity}
              tone="warning"
            />
            <StatCard
              icon={ShieldCheck}
              label="Complications"
              value="None detected"
              tone="success"
            />
            <StatCard
              icon={ClipboardList}
              label="Regions reviewed"
              value={`${report.findings.length} areas`}
            />
          </div>

          {/* Analysis timeline */}
          <Card>
            <CardContent className="p-5">
              <h3 className="mb-4 text-sm font-bold text-foreground">
                Analysis timeline
              </h3>
              <ol className="relative space-y-4 border-l border-border pl-5">
                {reportTimeline.map((t) => (
                  <li key={t.label} className="relative">
                    <span className="absolute -left-[27px] top-0.5 flex size-4 items-center justify-center rounded-full border-2 border-primary bg-background">
                      <span className="size-1.5 rounded-full bg-primary" />
                    </span>
                    <p className="text-sm font-semibold text-foreground">
                      {t.label}
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      {t.detail}
                    </p>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="mt-8 flex flex-col gap-3 sm:flex-row">
        <Button
          className="h-12 px-6 text-base"
          onClick={() => navigate('visual')}
        >
          <ScanEye className="size-4" />
          View Visual Explanation
          <ArrowRight className="size-4" />
        </Button>
        <Button
          variant="outline"
          className="h-12 px-6 text-base"
          onClick={() => navigate('qa')}
        >
          Ask a Question
        </Button>
      </div>
    </div>
  )
}
