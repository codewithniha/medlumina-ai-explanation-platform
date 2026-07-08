'use client'

import { Pill, ArrowRight, Activity, Link2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { PageHeader } from './page-header'
import { useApp } from '@/lib/app-context'
import { mockMedicines, mockSymptomLinks } from '@/lib/mock-data'

export function MedicineScreen() {
  const { navigate } = useApp()

  return (
    <div>
      <PageHeader
        title="Medicine & Symptoms"
        description="Understand what each prescribed medicine does and how your symptoms connect to the X-ray finding."
      />

      {/* Medicines */}
      <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-foreground">
        <Pill className="size-5 text-primary" />
        Your Prescribed Medicines
      </h2>
      <div className="mb-8 space-y-4">
        {mockMedicines.map((med) => (
          <Card key={med.name} className="transition-shadow hover:shadow-md">
            <CardContent className="p-5">
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-base font-bold text-foreground">
                  {med.name}
                </h3>
                <Badge variant="default">Prescribed</Badge>
              </div>
              <div className="mt-3 space-y-2.5">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    What it&apos;s for
                  </p>
                  <p className="mt-0.5 text-sm leading-relaxed text-foreground/90">
                    {med.purpose}
                  </p>
                </div>
                <div className="rounded-xl bg-primary/5 p-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-primary">
                    How it relates to your diagnosis
                  </p>
                  <p className="mt-0.5 text-sm leading-relaxed text-foreground/90">
                    {med.relation}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Symptom correlation */}
      <h2 className="mb-3 flex items-center gap-2 text-lg font-bold text-foreground">
        <Link2 className="size-5 text-primary" />
        How Your Symptoms Connect
      </h2>
      <Card>
        <CardContent className="p-5">
          <p className="mb-4 text-sm leading-relaxed text-muted-foreground">
            Each symptom you reported links to what the AI found on your X-ray.
          </p>
          <div className="space-y-3">
            {mockSymptomLinks.map((link) => (
              <div
                key={link.symptom}
                className="flex flex-col gap-2 sm:flex-row sm:items-center"
              >
                <Badge
                  variant="secondary"
                  className="w-fit justify-start py-1.5 text-sm"
                >
                  <Activity className="size-3.5 text-primary" />
                  {link.symptom}
                </Badge>
                <div className="flex flex-1 items-center gap-2">
                  <div className="hidden h-px flex-1 bg-gradient-to-r from-primary/40 to-transparent sm:block" />
                  <ArrowRight className="hidden size-4 shrink-0 text-primary/60 sm:block" />
                  <span className="rounded-lg bg-accent/60 px-3 py-1.5 text-sm font-medium text-accent-foreground">
                    {link.finding}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="mt-8">
        <Button
          size="lg"
          className="h-12 px-6 text-base"
          onClick={() => navigate('summary')}
        >
          View Final Summary
          <ArrowRight className="size-4" />
        </Button>
      </div>
    </div>
  )
}
