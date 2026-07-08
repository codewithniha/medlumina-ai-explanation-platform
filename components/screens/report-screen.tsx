'use client'

import {
  ScanEye,
  Lightbulb,
  Stethoscope,
  ClipboardList,
  ArrowRight,
  CheckCircle2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ConfidenceRing } from '@/components/confidence-ring'
import { PageHeader } from './page-header'
import { useApp } from '@/lib/app-context'
import { mockReport } from '@/lib/mock-data'

export function ReportScreen() {
  const { navigate } = useApp()
  const report = mockReport

  return (
    <div>
      <PageHeader
        eyebrow="Step 2 of 3"
        title="Your AI Report"
        description="Here is a structured reading of your X-ray, followed by a plain-language summary of what it means."
      />

      {/* Summary + confidence */}
      <Card className="mb-6 overflow-hidden">
        <CardContent className="flex flex-col items-center gap-6 p-6 sm:flex-row sm:items-center">
          <ConfidenceRing value={report.confidence} />
          <div className="flex-1 text-center sm:text-left">
            <Badge variant="warning" className="mb-2">
              <Stethoscope className="size-3.5" />
              Mild finding detected
            </Badge>
            <h2 className="text-lg font-bold text-foreground">
              Early-stage left lung infection
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              The AI is {report.confidence}% confident in this reading. A
              confidence score reflects how clearly the pattern appears — it is
              not a diagnosis and should be confirmed by your doctor.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Findings */}
      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center gap-2">
            <ClipboardList className="size-5 text-primary" />
            <CardTitle>Findings</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          {report.findings.map((f) => (
            <div
              key={f.region}
              className="flex gap-3 rounded-xl border border-border bg-secondary/40 p-4"
            >
              <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-semibold text-foreground">
                  {f.region}
                </p>
                <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
                  {f.detail}
                </p>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Impression */}
      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Stethoscope className="size-5 text-primary" />
            <CardTitle>Impression</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-[15px] leading-relaxed text-foreground/90">
            {report.impression}
          </p>
        </CardContent>
      </Card>

      {/* Plain summary */}
      <Card className="mb-8 border-primary/20 bg-primary/5">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Lightbulb className="size-5 text-primary" />
            <CardTitle>What this means for you</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-base leading-relaxed text-foreground/90 text-pretty">
            {report.plainSummary}
          </p>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Button
          size="lg"
          className="h-12 px-6 text-base"
          onClick={() => navigate('visual')}
        >
          <ScanEye className="size-4" />
          View Visual Explanation
          <ArrowRight className="size-4" />
        </Button>
        <Button
          size="lg"
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
