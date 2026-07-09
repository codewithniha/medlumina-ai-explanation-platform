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
import { mockReport, mockMedicines } from '@/lib/mock-data'

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
  const { resetSession } = useApp()

  return (
    <div className="mx-auto max-w-4xl">
      <div className="print:hidden">
        <PageHeader
          eyebrow="Step 6 of 6"
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
              <BrandLogo />
              <p className="mt-3 text-lg font-bold text-foreground">
                Patient Summary Report
              </p>
              <p className="text-xs text-muted-foreground">
                Plain-language explanation of your chest X-ray
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
                {mockReport.severity} finding
              </Badge>
            </div>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Scan type', value: 'Chest X-ray (PA)' },
              { label: 'Confidence', value: `${mockReport.confidence}%` },
              { label: 'Severity', value: mockReport.severity },
              { label: 'Medicines', value: `${mockMedicines.length} items` },
            ].map((item) => (
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
          <SummaryBlock icon={Lightbulb} title="Diagnosis explanation">
            Your chest X-ray shows a small area of early-stage infection
            (pneumonia) in the lower part of your left lung. Your heart, bones,
            and pleural spaces look normal. This was caught early and is very
            treatable.
          </SummaryBlock>

          <SummaryBlock icon={ScanEye} title="Key visual finding">
            {mockReport.findings[0].detail} The highlighted region on your
            visual explanation marks exactly where this appears.
          </SummaryBlock>

          <SummaryBlock icon={Pill} title="Medicine overview">
            <ul className="space-y-1.5">
              {mockMedicines.map((m) => (
                <li key={m.name} className="flex gap-2">
                  <Activity className="mt-0.5 size-3.5 shrink-0 text-primary" />
                  <span>
                    <span className="font-medium text-foreground">
                      {m.name}
                    </span>{' '}
                    — {m.purpose}{' '}
                    <span className="text-foreground/70">
                      ({m.dosage}, {m.timing})
                    </span>
                  </span>
                </li>
              ))}
            </ul>
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
