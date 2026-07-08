'use client'

import {
  Lightbulb,
  ScanEye,
  Pill,
  CalendarClock,
  Download,
  RotateCcw,
  CheckCircle2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { PageHeader } from './page-header'
import { useToast } from '@/components/ui/toast'
import { useApp } from '@/lib/app-context'
import { mockReport, mockMedicines } from '@/lib/mock-data'

const nextSteps = [
  'Take your full course of antibiotics, even if you feel better.',
  'Rest, drink plenty of fluids, and monitor your temperature.',
  'Follow up with your doctor in 2 weeks for a recovery check.',
  'Seek urgent care if breathing becomes difficult or fever worsens.',
]

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
    <div>
      <PageHeader
        eyebrow="Step 3 of 3"
        title="Your Summary"
        description="A complete, easy-to-keep overview of your results, medicines, and what to do next."
      />

      <Card className="mb-6 overflow-hidden">
        <div className="flex items-center gap-3 border-b border-border bg-primary/5 px-6 py-4">
          <CheckCircle2 className="size-5 text-primary" />
          <div>
            <p className="font-bold text-foreground">MedLumina Summary Report</p>
            <p className="text-xs text-muted-foreground">
              Sample document · Fictional demo data
            </p>
          </div>
          <Badge variant="warning" className="ml-auto">
            Mild finding
          </Badge>
        </div>
        <CardContent className="px-6 py-1">
          <SummaryBlock icon={Lightbulb} title="Diagnosis Explanation">
            Your chest X-ray shows a small area of early-stage infection
            (pneumonia) in the lower part of your left lung. Your heart, bones,
            and pleural spaces look normal. This was caught early and is very
            treatable.
          </SummaryBlock>

          <SummaryBlock icon={ScanEye} title="Key Visual Finding">
            {mockReport.findings[0].detail} The highlighted region on your
            visual explanation marks exactly where this appears.
          </SummaryBlock>

          <SummaryBlock icon={Pill} title="Medicine Overview">
            <ul className="space-y-1">
              {mockMedicines.map((m) => (
                <li key={m.name}>
                  <span className="font-medium text-foreground">{m.name}</span>{' '}
                  — {m.purpose}
                </li>
              ))}
            </ul>
          </SummaryBlock>

          <SummaryBlock icon={CalendarClock} title="Next-Step Guidance">
            <ul className="space-y-1.5">
              {nextSteps.map((step) => (
                <li key={step} className="flex gap-2">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                  <span>{step}</span>
                </li>
              ))}
            </ul>
          </SummaryBlock>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button
          size="lg"
          className="h-12 px-6 text-base"
          onClick={() =>
            toast({
              title: 'Summary downloaded',
              description: 'Your summary PDF has been saved (demo only).',
            })
          }
        >
          <Download className="size-4" />
          Download Summary as PDF
        </Button>
        <Button
          size="lg"
          variant="outline"
          className="h-12 px-6 text-base"
          onClick={() => {
            resetSession()
            toast({ title: 'New session started' })
          }}
        >
          <RotateCcw className="size-4" />
          Start New Session
        </Button>
      </div>

      <p className="mt-6 rounded-xl bg-muted/60 p-4 text-center text-xs leading-relaxed text-muted-foreground">
        MedLumina is a Final Year Project demo. All reports, images, medicines,
        and answers shown are fictional sample data and must not be used for
        real medical decisions.
      </p>
    </div>
  )
}
