'use client'

import { useState } from 'react'
import { PageHeader } from './page-header'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useApp } from '@/lib/app-context'
import {
  mockMedicines,
  mockSymptomLinks,
  type Medicine,
} from '@/lib/mock-data'
import { cn } from '@/lib/utils'
import {
  Pill,
  Clock,
  AlertTriangle,
  ChevronDown,
  ShieldAlert,
  Activity,
  ArrowRight,
  Link2,
  Info,
} from 'lucide-react'

const categoryStyles: Record<string, string> = {
  Antibiotic: 'bg-primary/15 text-primary border-primary/30',
  'Pain & Fever': 'bg-chart-4/15 text-chart-4 border-chart-4/30',
  'Cough Relief': 'bg-chart-2/15 text-chart-2 border-chart-2/30',
}

function MedicineCard({ medicine }: { medicine: Medicine }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card transition-colors hover:border-primary/40">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-4 p-5 text-left"
      >
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Pill className="h-6 w-6" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-foreground">
              {medicine.name}
            </h3>
            <span
              className={cn(
                'rounded-full border px-2.5 py-0.5 text-xs font-medium',
                categoryStyles[medicine.category] ??
                  'bg-muted text-muted-foreground border-border',
              )}
            >
              {medicine.category}
            </span>
          </div>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            {medicine.purpose}
          </p>
        </div>
        <ChevronDown
          className={cn(
            'mt-1 h-5 w-5 shrink-0 text-muted-foreground transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <div className="border-t border-border px-5 pb-5 pt-4">
          <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
            <div className="flex items-start gap-2">
              <Link2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-primary">
                  Why you were prescribed this
                </p>
                <p className="mt-1 text-sm leading-relaxed text-foreground">
                  {medicine.relation}
                </p>
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-border bg-muted/40 p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Activity className="h-4 w-4" />
                <span className="text-xs font-semibold uppercase tracking-wide">
                  Dosage
                </span>
              </div>
              <p className="mt-1.5 text-sm font-medium text-foreground">
                {medicine.dosage}
              </p>
            </div>
            <div className="rounded-xl border border-border bg-muted/40 p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Clock className="h-4 w-4" />
                <span className="text-xs font-semibold uppercase tracking-wide">
                  Timing
                </span>
              </div>
              <p className="mt-1.5 text-sm font-medium text-foreground">
                {medicine.timing}
              </p>
            </div>
          </div>

          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Possible side effects
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {medicine.sideEffects.map((effect) => (
                <span
                  key={effect}
                  className="rounded-full border border-border bg-background px-3 py-1 text-xs text-muted-foreground"
                >
                  {effect}
                </span>
              ))}
            </div>
          </div>

          <div className="mt-4 flex items-start gap-2 rounded-xl border border-chart-5/25 bg-chart-5/10 p-4">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-chart-5" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-chart-5">
                Important
              </p>
              <p className="mt-1 text-sm leading-relaxed text-foreground">
                {medicine.warnings}
              </p>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                <span className="font-medium text-foreground">
                  Interactions:{' '}
                </span>
                {medicine.interactions}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function MedicineScreen() {
  const { navigate } = useApp()

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        eyebrow="Step 5 of 6"
        title="Medicine & symptoms"
        description="Understand what your medicines do, how to take them, and how your symptoms connect to the findings on your scan."
      />

      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Pill className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold text-foreground">
              Your prescribed medicines
            </h2>
            <Badge variant="secondary" className="ml-1">
              {mockMedicines.length}
            </Badge>
          </div>
          {mockMedicines.map((medicine) => (
            <MedicineCard key={medicine.name} medicine={medicine} />
          ))}

          <div className="flex items-start gap-2 rounded-xl border border-border bg-muted/30 p-4">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <p className="text-xs leading-relaxed text-muted-foreground">
              This medication guidance is a plain-language explanation for
              understanding only. Always follow the exact instructions from your
              doctor or pharmacist, and never change your dose without medical
              advice.
            </p>
          </div>
        </div>

        <aside className="space-y-5">
          <div className="rounded-2xl border border-border bg-card p-5">
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary" />
              <h2 className="text-base font-semibold text-foreground">
                Symptom connections
              </h2>
            </div>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              How the symptoms you may feel relate to what the scan shows.
            </p>
            <ul className="mt-4 space-y-3">
              {mockSymptomLinks.map((link) => (
                <li
                  key={link.symptom}
                  className="rounded-xl border border-border bg-muted/40 p-3"
                >
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                    {link.symptom}
                  </div>
                  <div className="mt-1.5 flex items-center gap-1.5 pl-3.5 text-xs text-muted-foreground">
                    <ArrowRight className="h-3 w-3 text-primary/70" />
                    {link.finding}
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-2xl border border-chart-5/25 bg-chart-5/10 p-5">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-chart-5" />
              <h2 className="text-base font-semibold text-foreground">
                When to seek help
              </h2>
            </div>
            <ul className="mt-3 space-y-2 text-sm leading-relaxed text-muted-foreground">
              <li className="flex gap-2">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-chart-5" />
                Difficulty breathing or shortness of breath
              </li>
              <li className="flex gap-2">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-chart-5" />
                Fever lasting more than 3 days
              </li>
              <li className="flex gap-2">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-chart-5" />
                Chest pain that worsens or spreads
              </li>
              <li className="flex gap-2">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-chart-5" />
                Symptoms that get significantly worse
              </li>
            </ul>
          </div>
        </aside>
      </div>

      <div className="mt-10 flex flex-col gap-3 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between">
        <Button variant="ghost" onClick={() => navigate('qa')}>
          Back to questions
        </Button>
        <Button onClick={() => navigate('summary')} className="gap-2">
          View full summary
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
