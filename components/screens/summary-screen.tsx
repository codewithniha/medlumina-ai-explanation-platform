'use client'

import {
  Lightbulb,
  ScanEye,
  Pill,
  CalendarClock,
  Download,
  RotateCcw,
  CheckCircle2,
  Printer,
  Share2,
  Activity,
  ShieldCheck,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { PageHeader } from './page-header'
import { BrandLogo } from '@/components/brand-logo'
import { useToast } from '@/components/ui/toast'
import { useApp } from '@/lib/app-context'
import { mapAnalysisToReport } from '@/lib/report-mapper'

const nextSteps = [
  'Take your full course of antibiotics, even if you feel better.',
  'Rest, drink plenty of fluids, and monitor your temperature.',
  'Follow up with your doctor in 2 weeks for a recovery check.',
  'Seek urgent care if breathing becomes difficult or fever worsens.',
]

const reportDate = new Date().toLocaleDateString('en-US', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
})

function SummaryBlock({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="flex gap-4 border-b border-border py-5 last:border-0">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
        <Icon className="size-5" />
      </div>
      <div className="flex-1">
        <p className="font-semibold text-foreground">{title}</p>
        <div className="mt-1 text-sm leading-relaxed text-muted-foreground text-pretty">
          {children}
        </div>
      </div>
    </div>
  )
}

export function SummaryScreen() {
  const { toast } = useToast()
  const { resetSession, session, stepEyebrow } = useApp()
  const isPrescription = session.inputMode === 'prescription_only'

  // Real analysis mapping -- same function report-screen.tsx already uses
  // correctly. null when no real analysis has run yet (e.g. analysis
  // failed, or this is a prescription-only session with no image at all).
  const report = session.analysisResult ? mapAnalysisToReport(session.analysisResult) : null

  const headerCards = isPrescription
    ? [
        { label: 'Input type', value: 'Prescription' },
        { label: 'Medicines', value: `${session.medicines.length} items` },
        // Condition inference from medicines alone is currently paused
        // pending a methodology review (same reasoning as
        // report-screen.tsx's PrescriptionInsight) -- do not show a
        // fabricated condition or confidence number here either.
        { label: 'Possible condition', value: 'Under review' },
        { label: 'Inference confidence', value: 'Not available' },
      ]
    : [
        { label: 'Scan type', value: 'Chest X-ray (PA)' },
        { label: 'Confidence', value: report ? `${report.confidence}%` : 'Not available' },
        { label: 'Severity', value: report?.severity ?? 'Not available' },
        { label: 'Medicines', value: `${session.medicines.length} items` },
      ]

  return (
    <div className="mx-auto max-w-4xl">
      <div className="print:hidden">
        <PageHeader
          eyebrow={stepEyebrow('summary')}
          title="Your summary"
          description="A complete, easy-to-keep overview of your results, medicines, and what to do next. Print it or save it to share with your doctor."
        />
      </div>

      {/* Printable document */}
      <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm print:border-0 print:shadow-none">
        {/* Document header */}
        <div className="border-b border-border bg-gradient-to-br from-primary/10 to-transparent px-6 py-6 sm:px-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <BrandLogo showTagline={!isPrescription} />
              <p className="mt-3 text-lg font-bold text-foreground">
                Patient Summary Report
              </p>
              <p className="text-xs text-muted-foreground">
                {isPrescription
                  ? 'Plain-language explanation of your prescription'
                  : 'Plain-language explanation of your chest X-ray'}
              </p>
            </div>
            <div className="text-right text-xs text-muted-foreground">
              <p>
                <span className="font-medium text-foreground">Date:</span>{' '}
                {reportDate}
              </p>
              <p className="mt-0.5">
                <span className="font-medium text-foreground">Report ID:</span>{' '}
                ML-2026-0472
              </p>
              <Badge variant="warning" className="mt-2">
                {isPrescription
                  ? 'Inferred insight'
                  : report
                    ? `${report.severity} finding`
                    : 'Not yet analyzed'}
              </Badge>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {headerCards.map((item) => (
              <div
                key={item.label}
                className="rounded-xl border border-border bg-background/60 p-3"
              >
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {item.label}
                </p>
                <p className="mt-1 text-sm font-semibold text-foreground">
                  {item.value}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="px-6 py-1 sm:px-8">
          <SummaryBlock
            icon={Lightbulb}
            title={
              isPrescription
                ? 'Possible condition explanation'
                : 'Diagnosis explanation'
            }
          >
            {isPrescription ? (
              <>
                Inferring a possible condition purely from a medicine list is
                still under review to make sure it&apos;s done in a
                methodologically sound way. This section will be enabled once
                that review is complete -- nothing here should be treated as
                a diagnosis.
              </>
            ) : report ? (
              <>{report.plainSummary}</>
            ) : (
              <>
                No analysis has been completed for this session yet -- go
                back to Upload X-ray to run one.
              </>
            )}
          </SummaryBlock>

          {!isPrescription && report && (
            <SummaryBlock icon={ScanEye} title="Key visual finding">
              {report.findings[0]?.detail ?? 'No specific finding details are available for this analysis.'} The highlighted region on your
              visual explanation marks exactly where this appears.
            </SummaryBlock>
          )}

          <SummaryBlock icon={Pill} title="Medicine overview">
            {session.medicines.length > 0 ? (
              <ul className="space-y-1.5">
                {session.medicines.map((name) => (
                  <li key={name} className="flex gap-2">
                    <Activity className="mt-0.5 size-3.5 shrink-0 text-primary" />
                    <span>
                      <span className="font-medium text-foreground">{name}</span>{' '}
                      <span className="text-foreground/70">
                        (detailed purpose, dosage, and interactions aren&apos;t available yet in this demo)
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No medicines were entered for this session.</p>
            )}
          </SummaryBlock>

          <SummaryBlock icon={CalendarClock} title="Next-step guidance">
            <ul className="space-y-1.5">
              {nextSteps.map((step) => (
                <li key={step} className="flex gap-2">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                  <span>{step}</span>
                </li>
              ))}
            </ul>
          </SummaryBlock>

          <SummaryBlock icon={ShieldCheck} title="Important note">
            This summary is designed to help you understand your report. It is
            not a diagnosis and does not replace advice from your doctor. Please
            review it together with your healthcare provider.
          </SummaryBlock>
        </div>
      </div>

      {/* Actions */}
      <div className="mt-6 flex flex-col gap-3 sm:flex-row print:hidden">
        <Button
          className="gap-2"
          onClick={() =>
            toast({
              title: 'Summary downloaded',
              description: 'Your summary PDF has been saved (demo only).',
            })
          }
        >
          <Download className="size-4" />
          Download PDF
        </Button>
        <Button
          variant="outline"
          className="gap-2"
          onClick={() => window.print()}
        >
          <Printer className="size-4" />
          Print
        </Button>
        <Button
          variant="outline"
          className="gap-2"
          onClick={() =>
            toast({
              title: 'Share link created',
              description: 'A secure link was copied to your clipboard (demo).',
            })
          }
        >
          <Share2 className="size-4" />
          Share
        </Button>
        <Button
          variant="ghost"
          className="gap-2 sm:ml-auto"
          onClick={() => {
            resetSession()
            toast({ title: 'New session started' })
          }}
        >
          <RotateCcw className="size-4" />
          Start new session
        </Button>
      </div>

      <p className="mt-6 rounded-xl bg-muted/60 p-4 text-center text-xs leading-relaxed text-muted-foreground print:hidden">
        MedLumina is a Final Year Project demo. All reports, images, medicines,
        and answers shown are fictional sample data and must not be used for
        real medical decisions.
      </p>
    </div>
  )
}
