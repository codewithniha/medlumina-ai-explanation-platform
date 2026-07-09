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
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ConfidenceRing } from '@/components/confidence-ring'
import { PageHeader } from './page-header'
import { useApp } from '@/lib/app-context'
import { mockReport, reportTimeline } from '@/lib/mock-data'
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

export function ReportScreen() {
  const { navigate } = useApp()
  const report = mockReport

  return (
    <div>
      <PageHeader
        eyebrow="Step 2 of 6"
        title="Your AI Report"
        description="A structured reading of your X-ray, followed by a plain-language summary of what it means for you."
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
                    <Badge variant="secondary">Chest X-ray · PA view</Badge>
                  </div>
                  <h2 className="mt-3 text-xl font-bold text-foreground text-balance">
                    {report.diagnosis}
                  </h2>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    The AI is {report.confidence}% confident in this reading. A
                    confidence score reflects how clearly the pattern appears —
                    it is not a diagnosis and should be confirmed by your doctor.
                  </p>
                </div>
              </CardContent>
            </div>
          </Card>

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
              label="Confidence"
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
